# 每周清理一次下载文件夹里超过三十天的旧文件
import os
import time

下载目录 = "/volume1/下载"
期限 = 30 * 24 * 3600

for 文件 in os.listdir(下载目录):
    路径 = os.path.join(下载目录, 文件)
    if os.path.isfile(路径) and time.time() - os.path.getmtime(路径) > 期限:
        os.remove(路径)
        print("已删除", 路径)
