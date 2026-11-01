# 蒼究世界｜雙模式文字冒險

下載遊戲資料並交給支援檔案的GPT主持，在原創世界《蒼究世界》中自由冒險。

## 開始遊玩

1. 下載本專案的[文字匯入檔](蒼究世界_匯入即玩_v2.1.txt)（開啟檔案後使用下載按鈕），或從[Releases](https://github.com/tanyangbrocks/Cang---Novel---game/releases)取得已發布版本。尚無Release時可先下載repo中的TXT。
2. 在新的ChatGPT聊天上傳TXT，再傳送：

   > 請以這份檔案作為《蒼究世界》的遊戲規則與正典，載入後先讓我選擇「沉浸式故事冒險」或「沉浸式命運RPG」。

3. 選模式，再依提示創角。玩家不需在自己電腦安裝Python。

**沉浸式故事冒險**以自由敘事、角色互動與世界因果為主；**沉浸式命運RPG**包含配點、角色面板、技能、物品與統一機率判定。兩者均允許自由描述行動。

查看面板不花回合，底部接回目前劇情位置；有真正決策才列1～4個選項，沒有就自然推進。輸入「／存檔」保存完整進度，換聊天時重新提供遊戲資料與存檔。

檔案上傳不等於在所有介面永久安裝Skill。自動隨機、解壓與可下載存檔取決於GPT環境的工具；無實際隨機工具時，需玩家提供骰值，不能冒充真實抽樣。尚未完成任意帳號／平台的直接上傳與長期遊玩驗收。

## 資料與工具

- [主持入口](cangjiu-world/SKILL.md)
- [玩法規則](cangjiu-world/references/rpg.md)
- [作者裁定](cangjiu-world/references/author-decisions.md)
- `cangjiu-world/data/`：已整理的公開遊玩正典及示意地圖，使用相對路徑。
- `cangjiu-world/scripts/`：正典查詢、配點、D100、事件及存檔工具。
- `cangjiu-world/tests/`：資料與判定工具的隔離測試。

公開正典保留531個來源篇目的索引與內容／停用標記；指定停用內容不啟用。發布版採作者裁定並作最小必要內容調整，未將原始手稿或私人開發紀錄上傳。玩法數字不是原始世界規則。

## 本地開發

開發工具只需Python 3.10以上標準庫，不需第三方套件。以下在repo根目錄執行：

```sh
python -m unittest discover -s cangjiu-world/tests -v
python tools/check_release.py
python tools/build_release.py
```

產生的ZIP放在`dist/`，不提交執行存檔。修改已公開正典並完成審閱後，可執行`python tools/build_release.py --refresh-index`重新標定索引與來源指紋，再執行檢查。打包不會自行發布GitHub Release。

## 開發中的需求

下一階段為RPG的[自由時間與特殊情境](docs/rpg-time-design.md)：類人體系每月一個時間單位，依狀態取得行動點；特殊情境持續應對至結束。這份需求已保存，但行動點管理、活動成本及跨月自動結算尚未加入v2.1工具，不能把設計文件當作已完成程式。

## 權利

原創世界與作者內容的權利由其權利人保留。本repo未自行授予商用、改作或再授權權限；公開可讀取與下載不等同開放原創世界的一切利用方式。
