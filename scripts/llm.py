"""模型调用：本机 Claude Code（claude -p）或任何 OpenAI 兼容接口（火山方舟 / 豆包、通义、Kimi、OpenRouter……）。

选哪个后端，按顺序看：
  1. 环境变量 MANUAL_TO_3D_BACKEND = claude | openai | ark
  2. ~/.config/manual-to-3d/config.json 里的 "backend"
  3. 配了 API key（环境变量或配置文件）就用 OpenAI 兼容接口；否则本机有 claude 命令就用它

OpenAI 兼容接口的设置（环境变量优先，其次配置文件里同名的小写键）：
  MANUAL_TO_3D_BASE_URL    base_url    默认火山方舟 https://ark.cn-beijing.volces.com/api/v3
  MANUAL_TO_3D_API_KEY     api_key     也认 ARK_API_KEY
  MANUAL_TO_3D_MODEL       model       看图、生成场景用，必须能看图；方舟默认 doubao-seed-2-1-pro-260915
  MANUAL_TO_3D_MODEL_FAST  model_fast  翻译用，不填就用 model
  MANUAL_TO_3D_MAX_TOKENS  max_tokens  默认 32000

调用方传进来的 content 是 Anthropic 格式（text / image 块），这里按后端转换。
"""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG = Path("~/.config/manual-to-3d/config.json").expanduser()
ARK_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL = "doubao-seed-2-1-pro-260915"
SYSTEM = ("You are a precise engineering assistant that converts furniture assembly manuals into structured data. "
          "Reply with exactly one JSON object inside a ```json code fence and nothing else.")


def _config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def _setting(name, default=None):
    cfg = _config()
    return os.environ.get(f"MANUAL_TO_3D_{name.upper()}") or cfg.get(name) or default


def backend():
    b = (_setting("backend") or "").lower()
    if b in ("claude", "openai", "ark"):
        return "openai" if b == "ark" else b
    if _setting("api_key") or os.environ.get("ARK_API_KEY"):
        return "openai"
    if shutil.which("claude"):
        return "claude"
    raise SystemExit("没有可用的模型：装好并登录 Claude Code（claude 命令），或者在 ~/.config/manual-to-3d/config.json 里填 "
                     "OpenAI 兼容接口的 api_key 和能看图的 model（见 README「不用 Claude Code」一节）")


def describe():
    """给日志用的一行说明，不含密钥。"""
    if backend() == "claude":
        return "Claude Code（claude -p）"
    return f"{_setting('model', ARK_MODEL)} @ {_setting('base_url', ARK_URL)}"


def ask_model(content, model="opus", timeout=1800):
    """model 用 Claude 的叫法：opus = 看图和生成场景，sonnet = 翻译这类轻活。OpenAI 兼容后端按它选 model / model_fast。"""
    if backend() == "claude":
        return _ask_claude(content, model, timeout)
    name = _setting("model", ARK_MODEL)
    if model != "opus":
        name = _setting("model_fast", name)
    return _ask_openai(content, name, timeout)


def _ask_claude(content, model, timeout):
    msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
    cmd = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--model", model, "--tools", "", "--strict-mcp-config", "--system-prompt", SYSTEM]
    proc = subprocess.run(cmd, input=msg, capture_output=True, text=True, timeout=timeout)
    result = None
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            result = ev
    if not result or result.get("is_error"):
        raise RuntimeError(f"claude 调用失败：{(result or {}).get('result') or proc.stderr[-2000:]}")
    return result["result"]


def _to_openai(block):
    if block["type"] == "image":
        src = block["source"]
        return {"type": "image_url", "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}}
    return {"type": "text", "text": block["text"]}


def _ask_openai(content, model, timeout):
    key = _setting("api_key") or os.environ.get("ARK_API_KEY")
    if not key:
        raise SystemExit("OpenAI 兼容接口缺 api_key：设 MANUAL_TO_3D_API_KEY（或 ARK_API_KEY），或写进 ~/.config/manual-to-3d/config.json")
    url = _setting("base_url", ARK_URL).rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "max_tokens": int(_setting("max_tokens", 32000)),
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": [_to_openai(b) for b in content]}],
    }).encode()
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {key}",
                                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:1500]
            # 限流和网关错误等一会儿再试；额度用完、欠费这类 429 等也没用（方舟的 SetLimitExceeded、AccountOverdue）
            hard = any(k in detail for k in ("SetLimitExceeded", "AccountOverdue", "insufficient_quota", "QuotaExceeded"))
            if e.code in (429, 500, 502, 503, 504) and not hard and attempt < 3:
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(f"{model} 调用失败（HTTP {e.code}）：{detail}")
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError(f"{model} 输出被截断（max_tokens={_setting('max_tokens', 32000)}），调大 max_tokens 或换输出更长的模型")
    return choice["message"]["content"]
