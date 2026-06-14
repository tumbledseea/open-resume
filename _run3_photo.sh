#!/bin/bash
cd "d:/master/agent/OpenResume"
run() {
  local name="$1" profile="$2" company="$3" role="$4" query="$5" loc="$6" tmpl="$7"
  echo "===== START $name ($tmpl) ====="
  python resume_agent/cli.py pipeline \
    --profile-file "$profile" --photo "person/简历头像.png" \
    --company "$company" --role "$role" \
    --search-query "$query" --location "$loc" \
    --allow-network --auto-select --compile \
    --template "$tmpl" --min-match-score 0 \
    --project-dir "projects/refined_$name" > "projects/_log_$name.txt" 2>&1
  echo "===== DONE $name exit=$? ====="
  ls -la "projects/refined_$name/exports/resume.pdf" 2>/dev/null || echo "NO PDF for $name"
}
run accounting  person/profile_accounting.md "普华永道" "审计师"      "审计师 会计 上海"           "上海" teal_clean
run media      person/profile_media.md      "字节跳动" "品牌营销 内容运营" "品牌营销 内容运营 北京"    "北京" orange_warm
run education  person/profile_education.md  "新东方"   "高中语文教师"     "高中语文教师 杭州"          "杭州" purple_tech
echo "===== ALL DONE ====="
