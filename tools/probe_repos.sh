#!/usr/bin/env bash
# 探测 YHSome 名下可能的仓库是否存在
cd /d/OJ || exit 1
KEY=/d/OJ/data/state/ssh/github_ed25519
KNOWN=/d/OJ/data/state/ssh/known_hosts
export GIT_SSH_COMMAND="/usr/bin/ssh -i $KEY -o UserKnownHostsFile=$KNOWN -o IdentitiesOnly=yes -o ConnectTimeout=15"

for name in oj-ojojoj OJ oj MiniJudge mini-judge online-judge TinyWebDB-OJ OJ-OJOJOJ judge tinywebdb-oj; do
  out=$(timeout 25 git ls-remote "git@github.com:YHSome/$name.git" 2>&1 | head -2)
  if echo "$out" | grep -qi "Repository not found"; then
    echo "  ✘ YHSome/$name 不存在"
  elif echo "$out" | grep -qi "Permission denied\|Could not read"; then
    echo "  ? YHSome/$name 无法访问（可能不存在）"
  elif [ -z "$out" ]; then
    echo "  ✔ YHSome/$name 存在（空仓库）"
  else
    echo "  ✔ YHSome/$name 存在，远端 refs:"
    echo "$out" | sed 's/^/      /'
  fi
done
