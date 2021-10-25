# %%
import time
from datetime import datetime

用户名 = "用户名"
密码 = "密码"

#%%
from bilibili import Bilibili

b = Bilibili()
b.login(username=用户名, password=密码)

from bilibili_api import Verify

verify = Verify(sessdata=b._session.cookies['SESSDATA'], csrf=b._session.cookies['bili_jct'])

from bilibili_api import creative

import pandas as pd
import os
import numpy as np

comments_df: pd.DataFrame = None

blocklist: [int] = []

rules: (str, str) = []


def save(path: str):
    os.makedirs(path, exist_ok=True)
    comments_df.to_pickle(path + "/comments.pkl")
    np.save(path + "/blocklist.pkl", blocklist, allow_pickle=True)
    np.save(path + "/rules.pkl", rules, allow_pickle=True)


def load(path: str):
    global comments_df, blocklist, rules
    comments_df = pd.read_pickle(path + "/comments.pkl")
    blocklist = np.load(path + "/blocklist.pkl.npy", allow_pickle=True)
    rules = np.load(path + "/rules.pkl.npy", allow_pickle=True)


COMMENT_TYPE_MAP = {
    1: "视频",
    12: "专栏",
    11: "图片动态",
    17: "文字动态",
    14: "音频",
    19: "音频列表",
}

COMMENT_TYPE_REVERSE_MAP = {v: k for k, v in COMMENT_TYPE_MAP.items()}

COMMENT_TYPE_TYPE = pd.api.types.CategoricalDtype(
    categories=COMMENT_TYPE_MAP.values(),
    ordered=True
)

COMMENT_RELATION_MAP = {1: "路人", 2: "粉丝"}

COMMENT_RELATION_TYPE = pd.api.types.CategoricalDtype(
    categories=COMMENT_RELATION_MAP.values(),
    ordered=True
)

COMMENT_STATUS_TYPE = pd.api.types.CategoricalDtype(
    categories=["正常", "已删除"],
    ordered=True
)


def comments_to_df(comments):
    def get_from_comments(name):
        return [c[name] for c in comments]

    def convert_to_int(names):
        for name in names:
            df[name] = df[name].astype(int)

    df = pd.DataFrame({
        "回复文字": get_from_comments("message"),
        "用户 ID": get_from_comments("mid"),
        "用户昵称": get_from_comments("replier"),
        "视频 ID": get_from_comments("bvid"),
        "发布时间": get_from_comments("ctime"),
        "楼层": get_from_comments("floor"),
        "回复数目": get_from_comments("count"),
        "回复的评论 ID": get_from_comments("root"),
        "回复的内容 ID": get_from_comments("oid"),
        "修改时间": get_from_comments("mtime"),
        "上级评论 ID": get_from_comments("parent"),
        "点赞数": get_from_comments("like"),
        "用户头像": get_from_comments("uface"),
        "视频封面": get_from_comments("cover"),
        "视频标题": get_from_comments("title"),
        "关系": get_from_comments("relation"),
        "内容类型": get_from_comments("type"),
        "回复的评论对象": get_from_comments("root_info"),
        "上级评论对象": get_from_comments("parent_info"),
        "回复 ID": get_from_comments("id"),
    })
    convert_to_int([
        "用户 ID", "楼层", "回复数目", "回复的评论 ID", "回复的内容 ID", "上级评论 ID",
        "点赞数", "回复 ID"
    ])
    df.set_index("回复 ID", inplace=True)
    df["发布时间"] = pd.to_datetime(df["发布时间"])
    df["修改时间"] = pd.to_datetime(df["修改时间"])
    df["关系"] = df["关系"].map(COMMENT_RELATION_MAP).astype(COMMENT_RELATION_TYPE)
    df["内容类型"] = df["内容类型"].map(COMMENT_TYPE_MAP)
    df["评论状态"] = "正常"
    df["评论状态"] = df["评论状态"].astype(COMMENT_STATUS_TYPE)
    return df


def get_new_comments():
    new_comment_list = []
    for i in range(10):
        new_comments = creative.get_own_comments_raw("ctime", i + 1, verify=verify)
        if comments_df is not None:
            filtered_new_comments = [comment for comment in new_comments if comment['id'] not in comments_df.index]
        else:
            filtered_new_comments = new_comments
        new_comments_df = comments_to_df(filtered_new_comments)
        new_comment_list += [new_comments_df]
        print(f"找到新的 {len(filtered_new_comments)} 条评论")
        if len(new_comments) != len(filtered_new_comments):
            break
    return pd.concat(new_comment_list)


from bilibili_api import common, user


def delete_comments(comment_ids: [int]):
    df = comments_df.loc[comment_ids][["回复的内容 ID", "内容类型"]][comments_df["评论状态"] == "正常"]
    df["内容类型"] = df["内容类型"].map(COMMENT_TYPE_REVERSE_MAP)
    for type in df["内容类型"].unique():
        oid = df[df["内容类型"] == type]["回复的内容 ID"].to_list()
        rpid = df[df["内容类型"] == type].index.to_list()
        common.operate_comment("del", oid=oid, rpid=rpid, type_=[], raw_type=type, verify=verify)
        comments_df.loc[rpid, "评论状态"] = "已删除"


def blocklist_comments(comment_ids: [int]):
    blocklist_ids = set(comments_df.loc[comment_ids]["用户 ID"].to_list())
    blocklist_ids = blocklist_ids - set(blocklist)
    for blocklist_id in blocklist_ids:
        user.set_black(blocklist_id, True, verify)
        blocklist.append(blocklist_id)


def add_rule(rule, action, name, process_old = False):
    global rules
    if action not in ["拉黑", "删除"]:
        print("操作必须是 '拉黑' 或者 '删除' ")
        return
    new_rules = [
        (rule, action, name)
    ]
    if process_old:
        process_rule(comments_df, new_rules)
    rules += new_rules


def process_rule(local_comments_df, local_rules=None):
    if local_rules is None:
        local_rules = rules
    for rule, action, name in local_rules:
        match_list = local_comments_df.query(rule).index.to_list()
        if len(match_list) == 0:
            continue
        if action == "拉黑":
            print(f"评论符合 {name} 条件，拉黑中：{local_comments_df.loc[match_list]}")
            blocklist_comments(match_list)
        elif action == "删除":
            print(f"评论符合 {name} 条件，删除中：{local_comments_df.loc[match_list]}")
            delete_comments(match_list)


# ('拉黑我吧测试！' in `回复文字`) & 内容类型 == '专栏'

add_rule("'拉黑我吧测试！' in `回复文字`", "拉黑", "拉黑测试")
add_rule("'删除我吧测试！' in `回复文字`", "删除", "删除测试")

#%%
while True:
    print(datetime.now())
    new_comments_df = get_new_comments()
    if comments_df is None:
        comments_df = new_comments_df
    else:
        comments_df = comments_df.append(new_comments_df)
    process_rule(new_comments_df)
    print("等待 5 秒钟 CD")
    save("save")
    time.sleep(5)

