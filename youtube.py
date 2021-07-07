#!/usr/bin/python3

import json, os, time

CONFIG_DIR = f"{os.environ['HOME']}/.config/youtube/"
QUEUE_FILE = f"{CONFIG_DIR}youtube.json"

def dump_queue(Q):
    json.dump(Q, open(QUEUE_FILE, "w"), indent=2)

def read_queue():
    return json.load(open(QUEUE_FILE))

def get_subs():
    import json
    return json.load(open(f"{CONFIG_DIR}subs.json"))

def get_vids_from_sub(sub, from_time):
    import feedparser, time, html
    feed = feedparser.parse(sub["url"])
    new_vids = []
    for entry in feed.entries:
        try:
            unix_time = time.mktime(entry["published_parsed"])
        except:
            unix_time = time.time()
        if unix_time > from_time:
            new_vids.append({
                "channel": entry["author"],
                "title": html.unescape(entry["title"]),
                "link": entry["link"],
                "unix_time": unix_time,
            })
    return new_vids

def get_duration(url):
    # Naive processing without BS
    from urllib import request
    body = request.urlopen(url).read().decode("utf8")
    lines = body.split("\n")
    for line in lines:
        prop_ind = line.find('itemprop="duration"')
        if prop_ind != -1:
            start = line.find("PT", prop_ind) + 2
            end = line.find("S", start)
            time = line[start:end].split("M")
            time = int(time[0]) * 60 + int(time[1])
            return time
    return 0xAA

def parse_time(s):
    start = s.find("PT") + 2
    end = s.find("S", start)
    time = s[start:end].split("M")
    time = int(time[0]) * 60 + int(time[1])
    return time

def get_info(url):
    # Naive processing without BS
    from urllib import request
    import re, html
    body = request.urlopen(url).read().decode("utf8")
    lines = body.split("\n")
    for line in lines:
        prop_ind = line.find('itemprop="duration"')
        if prop_ind != -1:
            props = {m[0]: m[1] for m in re.findall(r"<meta itemprop=\"(.+?)\" content=\"(.+?)\">", line)}
            channel = re.search(r"<link itemprop=\"name\" content=\"(.+?)\">", line).group(1)
            duration = parse_time(props["duration"]) if "duration" in props else 0xAA
            return {
                "channel": channel,
                "title": html.unescape(props["name"]),
                "link": url,
                "unix_time": time.time(),
                "duration": duration,
            }

def id_from_url(url):
    id_ind = url.find("v=") + 2
    return url[id_ind:]

def thumbnail_path_from_url(url):
    id = id_from_url(url)
    return f"{CONFIG_DIR}{id}.jpg"

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
    subs = get_subs()
    for i, sub in enumerate(subs):
        print(f"Fetching subscribers {i+1}/{len(subs)}", end="\r")
        new_vids.extend(get_vids_from_sub(sub, last_fetch))
    print()
    Q["fetch_time"] = new_fetch
    Q["videos"] = (Q["videos"] if "videos" in Q else []) + new_vids
    print(f"Added {len(new_vids)} videos to queue")
    # dump_queue(Q)
    for i, video in enumerate(new_vids):
        print(f"Downloading thumbnails {i+1}/{len(new_vids)}", end="\r")
        link = video["link"]
        video["duration"] = get_duration(link)
        # dump_queue(Q)
        # download_thumbnail(link)
    ranks = {sub["name"]: sub["rank"] for sub in subs}
    Q["videos"].sort(key=lambda v:(ranks.get(v["channel"], 100), v["unix_time"], v["channel"]))
    Q["videos"].reverse()
    dump_queue(Q)
    print()

def add_vid(args):
    link = args.link
    Q = read_queue()
    Q["videos"].insert(0, get_info(link))
    dump_queue(Q)

def list_videos():
    print("{:20}{:80}{}".format("Channel", "Title", "Time"))
    for vid in json.load(open(QUEUE_FILE))["videos"]:
        print("{:20}{:80}{}".format(vid["channel"], vid["title"], time.ctime(vid["unix_time"])))

def get_entry_line(v, channel_width):
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

def fzf_get_lines():
    Q = read_queue()
    videos = Q["videos"]
    channel_width = max(map(lambda v:len(v["channel"]), videos)) + 2
    fzf_lines = [f"W {'Channel':{channel_width}}Title"]
    fzf_lines.extend(get_entry_line(v, channel_width) for v in videos)
    return "\n".join(fzf_lines)

def fzf_get_lines_cmd(args):
    print(fzf_get_lines())

def play_queue(args):
    import textwrap, itertools, glob
    from subprocess import Popen, PIPE
    while True:
        fzf_input = fzf_get_lines()
        fzf_binds = [
            ("ctrl-f", "page-down"),
            ("ctrl-b", "page-up"),
            ("ctrl-r", "reload(youtube.py fzf-lines)"),
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
            # "-s",
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
            Q = read_queue()
            Q["videos"] = list(filter(lambda v:v["link"] not in results, Q["videos"]))
            dump_queue(Q)
        else:
            # os.system("tput rmcup")
            print(f"Playing: {results[0]}")
            Popen("mpv --quiet " + " ".join(results), shell=True, stdout=None).wait()
    # os.system("tput rmcup")

def watched_video(args):
    from glob import glob
    Q = read_queue()
    if args.finished:
        Q["videos"] = list(filter(lambda v:v["link"] != args.link, Q["videos"]))
        id = id_from_url(args.link)

        for file in glob(f"{CONFIG_DIR}{id}.*"):
            os.remove(file)
        dump_queue(Q)
    else:
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
    add_cmd = sub_parsers.add_parser("add")
    add_cmd.add_argument("link")
    add_cmd.set_defaults(func=add_vid)
    fetch_cmd = sub_parsers.add_parser("fetch")
    fetch_cmd.set_defaults(func=renew_queue)
    mpv_watch_cmd = sub_parsers.add_parser("mpv_watched")
    mpv_watch_cmd.set_defaults(func=watched_video, finished=True)
    mpv_watch_cmd.add_argument("link")
    mpv_Watch_cmd = sub_parsers.add_parser("mpv_Watched")
    mpv_Watch_cmd.set_defaults(func=watched_video, finished=False)
    mpv_Watch_cmd.add_argument("link")
    mpv_Watch_cmd.add_argument("time")
    fzf_cmd = sub_parsers.add_parser("fzf-lines")
    fzf_cmd.set_defaults(func=fzf_get_lines_cmd)

    match = parser.parse_args()
    match.func(match)
