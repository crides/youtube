# Youtube Viewer

This utility is meant to work as a simple Youtube play queue for myself. It can fetch from RSS feeds of subscribers, and show a fzf interface for the actual playing.

The subscribers format has been changed to use a custom json format, which is a list of objects like `{ "url": string, "name": string, rank: int}` where `rank` is how much you want to sort the results in fzf by.
