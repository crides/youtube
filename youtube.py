#!/usr/bin/python3

import json, os, time, asyncio, aiohttp, async_timeout, pprint

CONFIG_DIR = f"{os.environ['HOME']}/.config/youtube/"
QUEUE_FILE = f"{CONFIG_DIR}youtube.json"

def dump_queue(Q):
    with open(QUEUE_FILE, "w") as out:
        json.dump(Q, out, indent=2)
        out.flush()
        os.fsync(out.fileno())

def read_queue():
    return json.load(open(QUEUE_FILE))

def get_subs():
    import json
    return json.load(open(f"{CONFIG_DIR}subs.json"))

async def fetch(session, url):
    async with async_timeout.timeout(5):
        async with await session.get(url) as resp:
            return await resp.text()

async def get_vids_from_sub(session, sub, from_time):
    import feedparser, time, html
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + sub["id"]
    feed = feedparser.parse(await fetch(session, url))
    new_vids = []
    for entry in feed.entries:
        try:
            unix_time = time.mktime(entry["published_parsed"])
        except:
            unix_time = time.time()
        if unix_time > from_time:
            new_vids.append({
                "channel": sub["name"],
                "title": html.unescape(entry["title"]),
                "link": entry["link"],
                "unix_time": unix_time,
            })
    return new_vids

async def get_duration(session, url):
    # Naive processing without BS
    body = await fetch(session, url)
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

async def get_info(session, url):
    # Naive processing without BS
    import re, html
    body = (await fetch(session, url)).read().decode("utf8")
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

def thumbnail_path(id):
    return f"{CONFIG_DIR}thumbs/{id}.jpg"

def rm_thumb(id):
    path = thumbnail_path(id)
    if os.path.exists(path):
        os.remove(path)

async def download_thumbnail(session, url):
    import os
    id = id_from_url(url)
    with open(thumbnail_path(id), "wb") as out:
        async with async_timeout.timeout(5):
            async with await session.get(f"https://i1.ytimg.com/vi/{id}/hq720.jpg") as resp:
                out.write(await resp.read())

async def renew_queue(args):
    Q = read_queue()
    last_fetch = Q["fetch_time"] if "fetch_time" in Q else 0
    new_fetch = time.time() + time.timezone
    new_vids = []
    subs = get_subs()
    print("Fetching subscribers...")
    async with aiohttp.ClientSession() as session:
        tasks = [get_vids_from_sub(session, sub, last_fetch) for sub in subs]
        new = await asyncio.gather(*tasks)
    old_vids = Q["videos"] if "videos" in Q else []
    for n in new:
        for v in n:
            for i, old in enumerate(new_vids):
                if old["link"] == v["link"]:
                    print(old["link"], old["title"])
                    old_vids[i]["title"] = v["title"]
                    old_vids[i]["unix_time"] = v["unix_time"]
                    old_vids[i]["duration"] = v["duration"]
                    break
            else:
                new_vids.append(v)
    print()
    Q["fetch_time"] = new_fetch
    Q["videos"] = old_vids + new_vids
    print(f"Added {len(new_vids)} videos to queue")
    # dump_queue(Q)
    print(f"Getting durations...")
    async with aiohttp.ClientSession() as session:
        for i, video in enumerate(new_vids):
            print(f"Downloading thumbnails {i+1}/{len(new_vids)}")
            link = video["link"]
            video["duration"] = await get_duration(session, link)
            await download_thumbnail(session, link)
    ranks = {sub["name"]: sub["rank"] for sub in subs}
    Q["videos"].sort(key=lambda v:(ranks.get(v["channel"], 100), v["unix_time"], v["channel"]))
    Q["videos"].reverse()
    dump_queue(Q)
    print()

def add_vid(args):
    link = args.link
    Q = read_queue()
    with aiohttp.ClientSession() as session:
        info = get_info(session, link)
    if info:
        Q["videos"].insert(0, info)
    dump_queue(Q)

def list_videos():
    print("{:20}{:80}{}".format("Channel", "Title", "Time"))
    for vid in json.load(open(QUEUE_FILE))["videos"]:
        print("{:20}{:80}{}".format(vid["channel"], vid["title"], time.ctime(vid["unix_time"])))

def get_entry_line(v, channel_width):
    return "\b".join([
        f"{'W ' if 'watched' in v else '  '}{v['channel']:{channel_width}}{v['title']}",
        v["link"],
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
    from subprocess import Popen, PIPE, DEVNULL
    import os, threading
    import ueberzug.lib.v0 as ueberzug
    link_fifo = f"{CONFIG_DIR}link_fifo.{os.getpid()}"
    preview_fifo = f"{CONFIG_DIR}preview_fifo.{os.getpid()}"
    os.mkfifo(link_fifo)
    os.mkfifo(preview_fifo)

    def preview_task(_link_fifo, _preview_fifo, videos):
        import textwrap
        space = " " * 37
        with ueberzug.Canvas() as c:
            uz = c.create_placement('youtube-preview', x=0, y=1, max_height=8)
            while True:
                with open(_link_fifo) as link_fifo:
                    for link in link_fifo:
                        id = id_from_url(link.strip())
                        vid = [v for v in videos if id in v["link"]][0]
                        duration = vid["duration"]
                        preview_lines = [
                            f"Channel: {vid['channel']}",
                            f"Title: {vid['title']}",
                            f"Publish Time: {time.ctime(vid['unix_time'])}",
                            f"Length: {duration//60:02}:{duration%60:02}",
                            f"Watched: {vid['watched']//60:02}:{vid['watched']%60:02}" if "watched" in vid else "",
                        ]
                        preview_lines = [w + "\n"
                                         for l in preview_lines
                                         for w in textwrap.wrap(l, width=87 - 4, initial_indent=space, subsequent_indent=space)]
                        preview_lines = preview_lines[:7]
                        preview_lines.extend((7 - len(preview_lines)) * ["\n"])
                        uz.path = thumbnail_path(id)
                        uz.visibility = ueberzug.Visibility.VISIBLE
                        with open(_preview_fifo, "w") as preview_fifo:
                            preview_fifo.write("".join(preview_lines))
    threading.Thread(target=preview_task, args=(link_fifo, preview_fifo, read_queue()["videos"]), daemon=True).start()
    while True:
        fzf_input = fzf_get_lines()
        fzf_binds = [
            ("ctrl-f", "page-down"),
            ("ctrl-b", "page-up"),
            ("ctrl-r", "reload(youtube.py fzf-lines)"),
            ("?", "execute(less {f})"),
        ]
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
            f"--preview='echo {{2}} >> {link_fifo} && head -n7 {preview_fifo}'",
            "--preview-window=up:7:wrap",
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
            for link in results:
                id = id_from_url(link)
                rm_thumb(id)
            dump_queue(Q)
        else:
            # os.system("tput rmcup")
            print(f"Playing: {results[0]}")
            proc = Popen(["mpv", "--script-opts=ytdl_hook-ytdl_path=yt-dlp",  "--ytdl-raw-options=external-downloader=aria2c,throttled-rate=300k,mark-watched="] + results, stdout=None, stdin=DEVNULL)
            proc.wait()
            time.sleep(0.5)
    # os.system("tput rmcup")
    os.remove(link_fifo)
    os.remove(preview_fifo)

def watched_video(args):
    # from glob import glob
    Q = read_queue()
    if args.finished:
        Q["videos"] = list(filter(lambda v:v["link"] != args.link, Q["videos"]))
        id = id_from_url(args.link)
        rm_thumb(id)
        # for file in glob(f"{CONFIG_DIR}{id}.*"):
        #     os.remove(file)
    else:
        for i, video in enumerate(Q["videos"]):
            if video["link"] == args.link:
                Q["videos"][i]["watched"] = int(float(args.time))
                break
        else:
            async def f():
                async with aiohttp.ClientSession() as session:
                    video = await get_info(session, args.link)
                    video["watched"] = int(float(args.time))
                    Q["videos"].insert(0, video)
            asyncio.run(f())
    dump_queue(Q)
    # pprint.pp(read_queue())

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
    fetch_cmd.set_defaults(func=lambda args: asyncio.run(renew_queue(args)))
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
