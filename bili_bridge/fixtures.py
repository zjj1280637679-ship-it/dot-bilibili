"""Pure, defensive metadata parsing and explicitly synthetic offline fixtures."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .contracts import Result

BV_RE = re.compile(r"BV[0-9A-Za-z]{10}\Z", re.ASCII)
MAX_HTML_BYTES = 2 * 1024 * 1024
UNSUPPORTED = ["search", "subtitles", "comments", "danmaku", "media", "private_account_data", "writes"]
FIXTURE_BVID = "BV1xx411c7mD"


def valid_bvid(value):
    return isinstance(value, str) and BV_RE.fullmatch(value) is not None


def evidence(target, source, *, fetched_at=None):
    return {
        "source": source,
        "evidence": {"url": f"https://www.bilibili.com/video/{target}/" if valid_bvid(target) else None,
                     "extraction": "window.__INITIAL_STATE__.videoData", "watched_video": False,
                     "retrieval": "not_applicable" if source == "offline_fixture" else "retrieved" if fetched_at is not None else "not_confirmed"},
        "freshness": {"retrieved_at": fetched_at, "kind": "synthetic" if source == "offline_fixture" else "live_snapshot" if fetched_at is not None else "not_retrieved"},
        "unsupported_features": list(UNSUPPORTED),
    }


def outcome(status, target, source, code, *, fetched_at=None):
    return Result(status, {**evidence(target, source, fetched_at=fetched_at), "reason": code}, code)


def decode_video_html(html, target, *, source="public_html", part=1, fetched_at=None):
    """Never execute page JavaScript or treat page text as instructions."""
    fail = lambda status, code: outcome(status, target, source, code, fetched_at=fetched_at)
    if not valid_bvid(target) or type(part) is not int or part < 1:
        return fail("rejected", "invalid_target_or_part")
    if not isinstance(html, str):
        return fail("blocked", "response_too_large_or_invalid")
    try:
        if len(html.encode("utf-8")) > MAX_HTML_BYTES:
            return fail("blocked", "response_too_large_or_invalid")
    except UnicodeError:
        return fail("unsupported", "initial_state_malformed")
    # Challenge markers, not generic words such as 'verify' found in normal scripts.
    lower = html.lower()
    if any(marker in lower for marker in ("访问受限", "安全验证", "人机验证", "验证码", "geetest_challenge", "<title>412", "<title>403")):
        return fail("blocked", "challenge_or_access_restricted")
    match = re.search(r"(?:window\.)?__INITIAL_STATE__\s*=\s*", html)
    if match is None:
        if any(marker in html for marker in ("视频不见了", "视频已删除", "稿件不存在")):
            return fail("blocked", "video_unavailable")
        return fail("unsupported", "initial_state_missing")
    try:
        state, _ = json.JSONDecoder(parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite_json"))).raw_decode(html[match.end():])
        json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, RecursionError, UnicodeError):
        return fail("unsupported", "initial_state_malformed")
    return state


def normalize_video_state(state, target, *, source="public_html", part=1, fetched_at=None):
    fail = lambda status, code: outcome(status, target, source, code, fetched_at=fetched_at)
    if not isinstance(state, dict) or not isinstance(state.get("videoData"), dict):
        return fail("unsupported", "unknown_video_schema")
    video = state["videoData"]
    if not video:
        return fail("blocked", "video_unavailable")
    if video.get("bvid") != target:
        return fail("unsupported", "video_identity_mismatch")
    if not isinstance(video.get("title"), str) or not isinstance(video.get("pages"), list):
        return fail("unsupported", "unknown_video_schema")
    pages = video["pages"]
    if len(pages) > 1000:
        return fail("unsupported", "too_many_parts")
    selected = [p for p in pages if isinstance(p, dict) and type(p.get("page")) is int and p["page"] == part]
    if not selected:
        return fail("unsupported", "part_unavailable")
    if len(selected) != 1 or type(selected[0].get("cid")) is not int or selected[0]["cid"] <= 0:
        return fail("unsupported", "unknown_part_schema")
    page = selected[0]
    # Copy only known scalar metadata, never URLs/scripts/account/session data.
    def scalar_fields(obj, fields):
        return {key: obj[key] for key in fields if key in obj and type(obj[key]) in (str, int, float, bool) and not (isinstance(obj[key], str) and len(obj[key]) > 20000)} if isinstance(obj, dict) else {}
    data = evidence(target, source, fetched_at=fetched_at)
    data["evidence"]["part"] = part
    data["evidence"]["cid"] = page["cid"]
    data["video"] = {**scalar_fields(video, ("bvid", "aid", "title", "desc", "duration", "pubdate")),
                     "owner": scalar_fields(video.get("owner"), ("mid", "name")),
                     "statistics": scalar_fields(video.get("stat"), ("view", "danmaku", "reply", "favorite", "coin", "share", "like")),
                     "part_count": len(pages), "selected_part": scalar_fields(page, ("page", "cid", "part", "duration"))}
    return Result("applied", data)


def parse_video_html(html, target, *, source="public_html", part=1, fetched_at=None):
    """Pure convenience composition; production plugin uses its module relay."""
    state = decode_video_html(html, target, source=source, part=part, fetched_at=fetched_at)
    if isinstance(state, Result):
        return state
    return normalize_video_state(state, target, source=source, part=part, fetched_at=fetched_at)


def read_fixture_html(target):
    if not valid_bvid(target):
        return outcome("rejected", target, "offline_fixture", "invalid_target_or_part")
    if target != FIXTURE_BVID:
        return outcome("unsupported", target, "offline_fixture", "fixture_not_found")
    return (Path(__file__).parent / "fixture_data" / "video.html").read_text(encoding="utf-8")


def read_fixture(target, *, part=1):
    if not valid_bvid(target):
        return outcome("rejected", target, "offline_fixture", "invalid_target_or_part")
    if target != FIXTURE_BVID:
        return outcome("unsupported", target, "offline_fixture", "fixture_not_found")
    html = (Path(__file__).parent / "fixture_data" / "video.html").read_text(encoding="utf-8")
    return parse_video_html(html, target, source="offline_fixture", part=part)
