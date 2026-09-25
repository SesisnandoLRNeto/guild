#!/usr/bin/env python3
"""Harnesses: how guild starts each agent CLI, read from config instead of hard-coded.

Defaults live in config/harnesses.json. ~/.guild/local/harnesses.json adds or replaces
harnesses with the same shape, so a new CLI (Gemini, opencode, aider...) is config, not code.

  harness.py list                         name, binary, hooks, tiers
  harness.py bin <name>                   the binary to look for on PATH
  harness.py hooks <name>                 exit 0 when the harness runs guild's hooks
  harness.py tier <name> <tier> [--effort] the model (or the effort) a tier maps to on that harness
  harness.py launch <name> KEY=VALUE...   bash lines that start (or resume) a quest
  harness.py tab <name> KEY=VALUE...      the command for a plain tab (resume=1 to reopen)

Launch lines expect the shell variables $model, $first and $GUILD_RESUME, which launch.sh sets.
"""
import json
import os
import re
import shlex
import sys

GUILD_HOME = os.environ.get("GUILD_HOME", os.path.expanduser("~/.guild"))
REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TIERS = ("plan", "build", "deep", "light")


def load():
    out = {}
    for path in (os.path.join(REPO, "config", "harnesses.json"),
                 os.path.join(GUILD_HOME, "local", "harnesses.json")):
        if os.path.exists(path):
            out.update({k: v for k, v in json.load(open(path)).items() if not k.startswith("_")})
    return out


def get(name):
    h = load().get(name)
    if not h:
        raise SystemExit(f"unknown harness {name} (known: {', '.join(sorted(load()))})")
    return h


def model_args(h):
    """The model flag, only when $model is set at run time: ${model:+--model "$model"}."""
    flag = h.get("model_flag", "")
    if not flag:
        return ""
    return "${model:+" + flag.replace("{model}", '"$model"') + "}"


def effort_args(h):
    """The effort flag, only when $effort is set at run time."""
    flag = h.get("effort_flag", "")
    if not flag:
        return ""
    return "${effort:+" + flag.replace("{effort}", '"$effort"') + "}"


def tier_of(h, tier):
    """A tier is a model name, or {"model": ..., "effort": ...}."""
    t = h.get("tiers", {}).get(tier)
    if isinstance(t, dict):
        return t.get("model", ""), t.get("effort", "")
    return (t or ""), ""


def expand(template, h, values):
    q = values.get("qdir", "")
    special = {
        "model_args": model_args(h),
        "effort_args": effort_args(h),
        "prompt": f'"$(cat {shlex.quote(q + "/prompt.md")})"',
        "kickoff": f'"$first Your brief is in {q}/brief.md"',
        "prompt_and_kickoff": f'"$(cat {shlex.quote(q + "/prompt.md")})"$\'\\n\\n\'"$first Your brief is in {q}/brief.md"',
        "prompt_file": shlex.quote(q + "/prompt.md"),
    }

    def sub(m):
        key = m.group(1)
        if key in special:
            return special[key]
        if key in values:
            return shlex.quote(values[key])
        raise SystemExit(f"harness template uses {{{key}}}, which guild does not know")
    return re.sub(r"\{([a-z_]+)\}", sub, template)


def env_lines(h):
    lines = []
    if h.get("env") or h.get("needs_env"):
        env_file = os.path.join(GUILD_HOME, "local", "env")
        lines.append(f"[ -f {shlex.quote(env_file)} ] && {{ set -a; . {shlex.quote(env_file)}; set +a; }}")
    for var in h.get("needs_env", []):
        lines.append(f'[ -n "${{{var}:-}}" ] || {{ echo "guild: no {var} (put it in {GUILD_HOME}/local/env)"; exec $SHELL; }}')
    for k, v in h.get("env", {}).items():
        # values may name other variables ($OPENROUTER_API_KEY), so they stay in double quotes
        lines.append(f'export {k}="{v}"')
    return lines


def parse_kv(args):
    return dict(a.split("=", 1) for a in args)


def main():
    cmd, rest = (sys.argv[1] if len(sys.argv) > 1 else "list"), sys.argv[2:]
    if cmd == "list":
        for name, h in sorted(load().items()):
            tiers = " ".join(f"{t}={'/'.join(x for x in tier_of(h, t) if x)}" for t in TIERS if t in h.get("tiers", {}))
            print(f"{name:<12} bin={h.get('bin', name):<8} hooks={'yes' if h.get('hooks') else 'no ':<3} {tiers}")
    elif cmd == "bin":
        print(get(rest[0]).get("bin", rest[0]))
    elif cmd == "hooks":
        sys.exit(0 if get(rest[0]).get("hooks") else 1)
    elif cmd == "tier":
        name, tier = rest[0], rest[1]
        if tier not in TIERS:
            raise SystemExit(f"unknown tier {tier} ({', '.join(TIERS)})")
        model, effort = tier_of(get(name), tier)
        if not model:
            raise SystemExit(f"harness {name} has no model for tier {tier}; set it under tiers in harnesses.json")
        print(effort if "--effort" in rest else model)
    elif cmd == "launch":
        h, values = get(rest[0]), parse_kv(rest[1:])
        lines = env_lines(h)
        start = expand(h["start"], h, values)
        resume = expand(h.get("resume") or h["start"], h, values)
        lines += [f'if [ "${{GUILD_RESUME:-}}" = 1 ]; then', f"  {resume}", "else", f"  {start}", "fi"]
        print("\n".join(lines))
    elif cmd == "tab":
        h, values = get(rest[0]), parse_kv(rest[1:])
        key = "tab_resume" if values.pop("resume", "") == "1" and h.get("tab_resume") else "tab"
        if key not in h:
            raise SystemExit(f"harness {rest[0]} has no '{key}' command for plain tabs")
        print("; ".join(env_lines(h) + [expand(h[key], h, values)]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
