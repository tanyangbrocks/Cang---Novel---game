# 共用專案進度

更新日期：2026-11-02。

正式 repo：https://github.com/tanyangbrocks/Cang---Novel---game.git ，分支 main。本文件的位置為 repo 內 docs/project-status.md。

目前版本2.2。支援「沉浸式故事冒險」與「沉浸式命運RPG」。故事模式維持自由敘事；RPG已實作每月AP、活動耗時、健康與疲勞上限、巢狀特殊情境、跨月刷新、年齡與存讀檔。26項本地測試通過；尚未完成長期實際遊玩驗收。

使用者接下來先試玩故事模式。遊玩入口為根目錄「蒼究世界_匯入即玩_v2.2.txt」。開發入口為 cangjiu-world/SKILL.md；作者裁定為 cangjiu-world/references/author-decisions.md。提供檔案不等於已創角或已開始劇情。

## 同步原則

專案位置、共用設定、程式進度與個別遊戲存檔是不同資料。各聊天開始時重新讀取可存取的最新文件；沒有工具就依使用者提供的檔案，不假裝同步。遊玩產生的事件屬於該局，不能自動升格為世界正典。作者新增裁定應另記並同步正式規則。

驗證：python -m unittest discover -s cangjiu-world/tests -v；python tools/check_release.py；python tools/build_release.py。
