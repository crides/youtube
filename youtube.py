#!/usr/bin/python3

import json, os, time

CONFIG_DIR = f"{os.environ['HOME']}/.config/youtube/"
QUEUE_FILE = f"{CONFIG_DIR}youtube.json"

def dump_queue(Q):
    json.dump(Q, open(QUEUE_FILE, "w"), indent=2)

def read_queue():
    return json.load(open(QUEUE_FILE))

def get_sub_urls():
    from xml.etree import ElementTree
    root = ElementTree.parse(f"{CONFIG_DIR}subscription_manager.xml").getroot()
    return [sub.get("xmlUrl") for sub in root[0][0]]

def get_vids_from_sub(url, from_time):
    import feedparser, time
    feed = feedparser.parse(url)
    new_vids = []
    for entry in feed.entries:
        unix_time = time.mktime(entry["published_parsed"])
        if unix_time > from_time:
            new_vids.append({
                "channel": entry["author"],
                "title": entry["title"],
                "link": entry["link"],
                "unix_time": unix_time,
            })
    new_vids.sort(key=lambda v:v["unix_time"])
    return new_vids

def get_duration(url):
    # Naive processing without BS
    from urllib import request
    body = request.urlopen(url).read().decode("utf8")
    lines = body.split("\n")
    for line in lines:
        if 'itemprop="duration"' in line:
            start = line.find("PT") + 2
            end = line.find("S")
            time = line[start:end].split("M")
            time = int(time[0]) * 60 + int(time[1])
            return time

def id_from_url(url):
    id_ind = url.find("v=") + 2
    return url[id_ind:]

def thumbnail_path_from_url(url):
    id = id_from_url(url)
    return f"{CONFIG_DIR}{id}.jpg"

def cache_video_path_from_url(url):
    id = id_from_url(url)
    return f"{CONFIG_DIR}{id}.mp4"

def download_thumbnail(url):
    from urllib import request
    import os
    id = id_from_url(url)
    request.urlretrieve(f"https://i1.ytimg.com/vi/{id}/hqdefault.jpg", thumbnail_path_from_url(url))

def renew_queue(args):
    Q = read_queue()
    last_fetch = Q["fetch_time"] if "fetch_time" in Q else 0
    new_fetch = time.time() + time.timezone
    new_vids = []
    sub_urls = get_sub_urls()
    for i, sub_url in enumerate(sub_urls):
        print(f"Fetching subscribers {i+1}/{len(sub_urls)}", end="\r")
        new_vids.extend(get_vids_from_sub(sub_url, last_fetch))
    print()
    Q["fetch_time"] = new_fetch
    Q["videos"] = (Q["videos"] if "videos" in Q else []) + new_vids
    print(f"Added {len(new_vids)} videos to queue")
    dump_queue(Q)
    for i, video in enumerate(new_vids):
        print(f"Downloading thumbnails {i+1}/{len(new_vids)}", end="\r")
        link = video["link"]
        video["duration"] = get_duration(link)
        dump_queue(Q)
        download_thumbnail(link)
    print()

def push_queue(args):
    from github import Github, InputFileContent
    from getpass import getpass
    queue_content = open(QUEUE_FILE).read()
    Q = json.loads(queue_content)
    username = input("Username: ")
    passwd = getpass("Password: ")
    g = Github(username, passwd)
    user = g.get_user()
    try:
        if "gist_id" in Q:
            gist_id = Q["gist_id"]
            gist = g.get_gist(gist_id)
            gist_files = {QUEUE_FILE: InputFileContent(queue_content, QUEUE_FILE)}
            gist.edit("Youtube Queue", gist_files)
        else:
            gist_files = {QUEUE_FILE: InputFileContent("Nothing", QUEUE_FILE)}
            gist = user.create_gist(False, gist_files, "Youtube Queue")
            print(f"Created new gist: {gist_id}")
            Q["gist_id"] = gist.id
            queue_content = json.dumps(Q, indent=2)
            dump_queue(Q)
            gist_files = {QUEUE_FILE: InputFileContent(queue_content, QUEUE_FILE)}
            gist.edit("Youtube Queue", gist_files)
    except Exception as e:
        print("Github error:", e)

def pull_queue(args):
    from getpass import getpass
    from github import Github
    Q = read_queue()
    username = input("Username: ")
    passwd = getpass("Password: ")
    g = Github(username, passwd)
    user = g.get_user()
    try:
        if "gist_id" in Q:
            gist_id = Q["gist_id"]
            gist = g.get_gist(gist_id)
            open(QUEUE_FILE, "w").write(gist.files[QUEUE_FILE].content)
        else:
            print("No Gist ID")
    except Exception as e:
        print("Github error:", e)

def list_videos():
    print("{:20}{:80}{}".format("Channel", "Title", "Time"))
    for vid in json.load(open(QUEUE_FILE))["videos"]:
        print("{:20}{:80}{}".format(vid["channel"], vid["title"], time.ctime(vid["unix_time"])))

def play_queue(args):
    import textwrap, itertools, glob
    from subprocess import Popen, PIPE
    while True:
        Q = read_queue()
        videos = Q["videos"]
        if len(videos) == 0:
            print("No videos in queue.")
            break
        channel_width = max(map(lambda v:len(v["channel"]), videos)) + 2
        fzf_lines = [f"W {'Channel':{channel_width}}Title"]
        def get_entry_line(v):
            import time
            duration = v["duration"]
            return "\b".join([
                f"{'W ' if 'watched' in v else '  '}{v['channel']:{channel_width}}{v['title']}",
                v["link"],
                v["channel"],
                v["title"],
                time.ctime(v["unix_time"]),
                f"{duration//60:02}:{duration%60:02}",
                f"Watched: {v['watched']//60:02}:{v['watched']%60:02}" if "watched" in v else "",
            ])
        fzf_lines.extend(get_entry_line(v) for v in videos)
        fzf_input = "\n".join(fzf_lines)
        fzf_binds = [
            ("ctrl-f", "page-down"),
            ("ctrl-b", "page-up"),
            ("?", "execute(less {f})"),
        ]
        # ueberzug_arg = "\\t".join(f"{t[0]}\\t{t[1]}" for t in [
        #     ("x", "0"),
        #     ("y", "4"),
        #     ("identifier", "youtube-preview"),
        #     ("max_width", "$FZF_PREVIEW_COLUMNS"),
        #     ("max_height", "$FZF_PREVIEW_LINES"),
        #     ("action", "add"),
        #     ("path", "/home/steven/.config/youtube/8zoPyMAsVek.jpg"),
        # ])
        fzf_preview_cmds = "; ".join([
            "echo Channel: {3}",
            "echo Title: {4}",
            "echo Publish Time: {5}",
            "echo Length: {6}",
            "echo {7}",
            # f"{{echo \"{ueberzug_arg}\"; sleep 2;}} | ueberzug layer -p simple",
        ])
        fzf_opts = [
            "-e",   # --exact
            "-s",
            # "--no-clear",
            "-m",   # --multi
            "--reverse",
            "--header-lines=1",
            "-d \b",  # --delimiter
            "--with-nth=1",
            "--expect=del,enter",
            "--info=inline",
            f"--preview='{fzf_preview_cmds}'",
            "--preview-window=down:5:wrap",
        ]
        fzf_opts.append("--bind='" + ",".join(f"{b[0]}:{b[1]}" for b in fzf_binds) + "'")
        fzf_cmd = f"fzf {' '.join(fzf_opts)}"
        fzf = Popen(fzf_cmd, stdin=PIPE, stdout=PIPE, shell=True)
        fzf.stdin.write(bytes(fzf_input, "utf8"))
        fzf.stdin.close()
        results = fzf.stdout.readlines()
        if len(results) == 0:
            break
        key = results.pop(0)[:-1].decode("utf8")
        for i, line in enumerate(results):
            results[i] = line[:-1].split(b"\b")[1].decode("utf8")
        if key == "del":
            Q["videos"] = list(filter(lambda v:v["link"] not in results, videos))
            dump_queue(Q)
        elif key == "enter":
            # os.system("tput rmcup")
            Popen("mpv --fs --quiet " + " ".join(results), shell=True, stdout=None).wait()
    # os.system("tput rmcup")

def watched_video(args):
    from glob import glob
    Q = read_queue()
    if args.finished:
        Q["videos"] = list(filter(lambda v:v["link"] != args.link, Q["videos"]))
        id = id_from_url(args.link)
        print(args.link, id)

        for file in glob(f"{CONFIG_DIR}{id}.*"):
            os.remove(file)
        dump_queue(Q)
    else:
        print("'" + args.time + "'")
        for i, video in enumerate(Q["videos"]):
            if video["link"] == args.link:
                Q["videos"][i]["watched"] = int(float(args.time))
                break
        dump_queue(Q)

if __name__ == "__main__":
    import sys
    from argparse import ArgumentParser
    parser = ArgumentParser()
    sub_parsers = parser.add_subparsers()
    play_cmd = sub_parsers.add_parser("play")
    play_cmd.set_defaults(func=play_queue)
    fetch_cmd = sub_parsers.add_parser("fetch")
    fetch_cmd.set_defaults(func=renew_queue)
    push_cmd = sub_parsers.add_parser("push")
    push_cmd.set_defaults(func=push_queue)
    pull_cmd = sub_parsers.add_parser("pull")
    pull_cmd.set_defaults(func=pull_queue)
    mpv_watch_cmd = sub_parsers.add_parser("mpv_watched")
    mpv_watch_cmd.set_defaults(func=watched_video, finished=True)
    mpv_watch_cmd.add_argument("link")
    mpv_Watch_cmd = sub_parsers.add_parser("mpv_Watched")
    mpv_Watch_cmd.set_defaults(func=watched_video, finished=False)
    mpv_Watch_cmd.add_argument("link")
    mpv_Watch_cmd.add_argument("time")

    match = parser.parse_args()
    match.func(match)
