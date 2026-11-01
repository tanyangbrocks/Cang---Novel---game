# 事件與持久化存檔2.0

完整存檔以 `campaigns/<id>/state.json` 保存，含schema_version、rules_version、世界線ID、initial、snapshot、events、checks、revision。每事件具ID、順序、輸入、來源、前筆指紋及本筆指紋；重播事件可核對快照。指紋是完整性檢查，不是防惡意篡改簽章。JSON是主持私有資料，不直接向玩家展示。

工具每次修改用獨占鎖、暫存、落盤及原子替換，上一版另存history。寫入失敗不能宣稱完成；殘留lock須先核對程序與最後存檔，不隨意刪除。對話歷史不是唯一資料庫。查詢不寫入、不前進時間。

## 操作

在套件目錄執行；以下只是命令形式，不在未選模式時擅自執行：

```text
python scripts/game.py new --id <worldline> --mode rpg --name <姓名>
python scripts/game.py build --id <worldline> --data <配點.json>
python scripts/game.py finalize --id <worldline> --data <玩家已確認的開局.json>
python scripts/game.py panel --id <worldline> --section 面板
python scripts/game.py check --id <worldline> --data <判定.json>
python scripts/game.py commit --id <worldline> --data <事件.json>
python scripts/game.py verify --id <worldline>
python scripts/game.py export --id <worldline> --audience host --output <新路徑.json>
```

所有修改JSON需 `event_id`、`expected_revision`（目前事件數）。資料以UTF-8檔案傳入。build需八項attributes與總6點skills；finalize需player_confirmed=true、scene（location/summary/choices）、source_refs、identity。source_refs可引用原文ID、作者裁定或明標的新增設定／玩法版本。

check需actor_id、gate=uncertain、basis、obstacle_id、attribute_name、attribute、skill_name、rank、difficulty、required_rank、context、luck。必須與當前角色卡相符，難度與依據先固定；工具使用系統隨機抽D100並立即保存。相同event_id及內容會回原結果，任何新檢定須先結算或放棄未決檢定。

commit需reason、source_refs、actor_id、event_type、elapsed_seconds；可含check_id及狀態變更。entities為現有人物的欄位更新；new_entities為有來源的新人物；items、relations、reputation、pending、additions是該部分的完整替換集合，不是局部差分，先讀原集合以免遺失紀錄。scene完整保存當前位置、摘要與有效選單。entities中的位置變更需movement等相應事件及scene一起更新。

放棄已擲行動也用commit結算check_id，reason明示放棄，按實際已付代價處理；不能把放棄當成免費重抽。死亡改回非死亡需event_type=revival、mechanism與來源，主持仍須實際核對正典及儀式完成證據。程式檢查必要欄位不等於自動證明復活合法。

人物的knowledge（主觀認知）、truth（主持事實）、beliefs（相信）、public_claims（說法）、goals與personality可透過entities更新。能力卡保存在abilities，玩家可見部分放public。關係／勢力評價同樣以public分隔可見內容。資料來源應標明於sources。若需更新超出工具現有欄位的複雜人物卡，先擴充schema並驗證，不直接改JSON繞過日誌。遊戲事實一旦確立不能事後為選擇改寫。

## 恢復與匯出

讀檔先verify，確認分支、正典指紋、規則版本與未決檢定。回到scene，不重新創角、重抽或扣同次消耗。需跨機攜帶完整主持存檔及相應正典、作者裁定與套件版本。`export --audience player`僅匯出可見面板，不足以完整續玩；host匯出包含秘密，交給主持載入，不能把全文當玩家面板。

無工具環境可按[狀態模板](state-template.md)輸出完整可保存資料，但必須明示未寫檔。D100可由玩家提供；無實際抽樣就保留待判定。不宣稱檔案打包成功已等於全平台安裝或長期驗收通過。


RPG自由時間、AP、活動耗時、特殊情境及跨月處理遵循[時間與行動點](rpg-time.md)。故事模式不套用AP。RPG總覽另顯示年齡、月內時間、AP上限／剩餘、當前活動與情境。
