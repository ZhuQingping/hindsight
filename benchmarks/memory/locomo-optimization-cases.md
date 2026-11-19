# LoCoMo 优化前后判定变化逐题记录

本附录对应[优化目的与效果记录](locomo-optimization.md)，列出全部 **36 道原有错题转对**及 **13 道新增错题**。结果取自最终完整1540题导出，不拼接早期不完整成绩。题号为原始零基下标。

“转对”和“回退”均指固定 AMB LoCoMo 裁判的布尔判定；不是 BEAM 的 rubric 半分门槛。下面的 gold 是原始评分参考，并不保证没有原文歧义。来源检查不改分，也不把分数变化直接认定为检索原因。

原始参考证据 ID 的出现情况仅用于事后诊断：完整出现不等于语义蕴含，未完整出现也不排除其他等价证据。候选原文和打包器没有读取 QA gold 或证据标注。

## 结果总览

| 状态 | 题数 |
| --- | ---: |
| 两轮均通过 | 1406 |
| 原有错题转对 | 36 |
| 新增错题 | 13 |
| 两轮均未通过 | 85 |
| 合计 | 1540 |

最终通过题数 1419 → 1442；净增 23 题。窗口方案仍有 98 道错题，即 85 道持续错题和 13 道新增错题。完整98题来源检查位于[原始诊断文件](results/locomo1540-window-diagnostics-20261119.json)，不在本附录重复展开。

## 原有错题转对

以下36题均由未通过变为通过。29题沿用已有专项来源检查，另7题在11月20日补查两轮保存的上下文。来源比较支持局部定位，不能替代单变量实验来确定因果。

| 题号与详情 | 问题 | 来源检查状态 |
| --- | --- | --- |
| [conv-26_q21](#conv-26-q21) | When did Caroline have a picnic? | 已有来源检查，见下方边界 |
| [conv-26_q26](#conv-26-q26) | When did Melanie read the book "nothing is impossible"? | 已有来源检查，见下方边界 |
| [conv-26_q78](#conv-26-q78) | What items has Melanie bought? | 已有来源检查，见下方边界 |
| [conv-26_q80](#conv-26-q80) | When did Melanie buy the figurines? | 已有来源检查，见下方边界 |
| [conv-26_q85](#conv-26-q85) | What are Caroline's plans for the summer? | 已有来源检查，见下方边界 |
| [conv-26_q132](#conv-26-q132) | How long has Melanie been creating art? | 已有来源检查，见下方边界 |
| [conv-26_q133](#conv-26-q133) | What precautionary sign did Melanie see at the café? | 已有来源检查，见下方边界 |
| [conv-26_q135](#conv-26-q135) | What setback did Melanie face in October 2023? | 已有来源检查，见下方边界 |
| [conv-30_q13](#conv-30-q13) | When did Gina open her online clothing store? | 已有来源检查，见下方边界 |
| [conv-30_q37](#conv-30-q37) | When did Gina mention Shia Labeouf? | 已有来源检查，见下方边界 |
| [conv-30_q44](#conv-30-q44) | What does Gina say about the dancers in the photo? | 已有来源检查，见下方边界 |
| [conv-30_q73](#conv-30-q73) | How does Gina describe the feeling that dance brings? | 已有来源检查，见下方边界 |
| [conv-41_q0](#conv-41-q0) | Who did Maria have dinner with on May 3, 2023? | 已有来源检查，见下方边界 |
| [conv-41_q4](#conv-41-q4) | When did John join the online support group? | 已有来源检查，见下方边界 |
| [conv-41_q45](#conv-41-q45) | Would John be open to moving to another country? | 已有来源检查，见下方边界 |
| [conv-41_q95](#conv-41-q95) | What activity did Maria and her mom do together in May 2023? | 已有来源检查，见下方边界 |
| [conv-41_q123](#conv-41-q123) | What did Maria plan to do later on the evening of 7 July, 2023? | 已有来源检查，见下方边界 |
| [conv-42_q60](#conv-42-q60) | What Console does Nate own? | 已有来源检查，见下方边界 |
| [conv-43_q5](#conv-43-q5) | Based on Tim's collections, what is a shop that he would enjoy visiting in New York city? | 已有来源检查，见下方边界 |
| [conv-44_q39](#conv-44-q39) | What did Audrey get wtih having so many dogs? | 已有来源检查，见下方边界 |
| [conv-47_q16](#conv-47-q16) | What is the game with different colored cards that was John talking about with James? | 已有来源检查，见下方边界 |
| [conv-47_q71](#conv-47-q71) | What did James offer to do for John regarding pets? | 已有来源检查，见下方边界 |
| [conv-47_q147](#conv-47-q147) | What did John suggest James practice before playing FIFA 23 together? | 已有来源检查，见下方边界 |
| [conv-48_q74](#conv-48-q74) | What do Deborah and Jolene plan to try when they meet in a new cafe? | 已有来源检查，见下方边界 |
| [conv-48_q75](#conv-48-q75) | What card game is Deborah talking about? | 已有来源检查，见下方边界 |
| [conv-48_q99](#conv-48-q99) | What do Deborah and Jolene plan to try when they meet in a new cafe? | 已有来源检查，见下方边界 |
| [conv-48_q119](#conv-48-q119) | What picture did Jolene share related to feeling overwhelmed? | 已有来源检查，见下方边界 |
| [conv-48_q174](#conv-48-q174) | Why did Jolene have to reschedule their meeting with Deborah on September 8, 2023? | 已有来源检查，见下方边界 |
| [conv-49_q11](#conv-49-q11) | What health issue did Sam face that motivated him to change his lifestyle? | 已有来源检查，见下方边界 |
| [conv-49_q57](#conv-49-q57) | Which US state was Sam travelling in during October 2023? | 已有来源检查，见下方边界 |
| [conv-49_q99](#conv-49-q99) | What did Evan suggest Sam to check out for insights into his dream? | 已有来源检查，见下方边界 |
| [conv-49_q123](#conv-49-q123) | What adventurous theme is emerging in Evan's life as mentioned by Sam? | 已有来源检查，见下方边界 |
| [conv-49_q141](#conv-49-q141) | What did Evan suggest Sam should keep doing to find his own version of love? | 已有来源检查，见下方边界 |
| [conv-49_q145](#conv-49-q145) | What did Evan offer to share with Sam after talking about healthy snacks? | 已有来源检查，见下方边界 |
| [conv-49_q153](#conv-49-q153) | What did Evan share a photo of that was taken on a camping trip? | 已有来源检查，见下方边界 |
| [conv-50_q134](#conv-50-q134) | What is the toughest part of car restoration according to Dave? | 已有来源检查，见下方边界 |

## 新增错题

以下13题均由通过变为未通过，均有已有来源检查。

| 题号与详情 | 问题 |
| --- | --- |
| [conv-26_q68](#conv-26-q68) | How long has Melanie been practicing art? |
| [conv-41_q94](#conv-41-q94) | What kind of food did Maria have on her dinner spread iwth her mother? |
| [conv-42_q23](#conv-42-q23) | Which of Joanna's screenplay were rejected from production companies? |
| [conv-43_q48](#conv-43-q48) | When did John get an ankle injury in 2023? |
| [conv-43_q49](#conv-43-q49) | How many times has John injured his ankle? |
| [conv-43_q166](#conv-43-q166) | What is John's favorite book series? |
| [conv-44_q37](#conv-44-q37) | When did Audrey get into an accident in the park? |
| [conv-44_q55](#conv-44-q55) | When did Andrew make his dogs a fun indoor area? |
| [conv-47_q56](#conv-47-q56) | Which of James's family members have visited him in the last year? |
| [conv-48_q188](#conv-48-q188) | What outdoor activity did Jolene suggest doing together with Deborah? |
| [conv-49_q104](#conv-49-q104) | What food did Sam share a photo of on 19 August, 2023? |
| [conv-50_q130](#conv-50-q130) | How does Calvin balance his job and personal life? |
| [conv-50_q136](#conv-50-q136) | When did Dave sell the car he restored last year? |

## 转对题详细对照

### conv-26-q21

原始题号：`conv-26_q21`。类别：2。判定：未通过 → 通过。

问题：When did Caroline have a picnic?

原始评分参考：

> ["The week before 6 July 2023"]

**基线答案**

> The provided memories do not state when Caroline had a picnic.

**窗口方案答案**

> Caroline had a picnic with friends and family during June 26–July 2, 2023.

**原始裁判理由**

- 基线：The generated answer says the date is unknown, whereas the gold answer specifies the week before 6 July 2023.
- 窗口：June 26–July 2, 2023 is the calendar week before July 6, 2023, matching the gold answer.

原版答案 F1：0.000000 → 0.125000。

**来源核查与归因边界**

旧打包中无 picnic 原句，新窗口保留 D6:11 的 We even had a picnic last week，并保留该 session 日期用于解释时间；答案由未知变为 June26–July2。参考原句旧 recall 也未返回，支持原文返回和最终可见性改善；未单独隔离预算与窗口各自贡献。

原始来源检查标签：`supplemental_recorded_context_review_20261120`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D6:11 | D6:11 |
| recall 原文中出现的参考 ID | 无 | D6:11 |
| 最终上下文中出现的参考 ID | 无 | D6:11 |
| 最终记忆 tokens | 7716 | 7990 |

### conv-26-q26

原始题号：`conv-26_q26`。类别：2。判定：未通过 → 通过。

问题：When did Melanie read the book "nothing is impossible"?

原始评分参考：

> [2022]

**基线答案**

> Melanie was reading a book Caroline recommended by October 13, 2023, during her recovery from a September 2023 injury. However, the memories do not confirm that its title was “Nothing Is Impossible” or specify exactly when she read it.

**窗口方案答案**

> Melanie read "Nothing Is Impossible" in 2022.

**原始裁判理由**

- 基线：The generated answer suggests 2023 and uncertainty rather than identifying 2022, the year specified in the gold answer.
- 窗口：The generated answer gives 2022, which exactly matches the gold answer.

原版答案 F1：0.000000 → 0.250000。

**来源核查与归因边界**

旧输入无 D7:8；新窗口保留 This book I read last year，模型据2023年会话答2022。该消息和caption没有直接写出 Nothing Is Impossible 书名，书籍指代仍依赖问题及上下文；支持时间线索恢复，不能称已唯一确认书名。

原始来源检查标签：`supplemental_recorded_context_review_20261120`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D7:8 | D7:8 |
| recall 原文中出现的参考 ID | 无 | D7:8 |
| 最终上下文中出现的参考 ID | 无 | D7:8 |
| 最终记忆 tokens | 7987 | 7977 |

### conv-26-q78

原始题号：`conv-26_q78`。类别：1。判定：未通过 → 通过。

问题：What items has Melanie bought?

原始评分参考：

> ["Figurines, shoes"]

**基线答案**

> The provided memories do not specify any items Melanie has bought.

**窗口方案答案**

> Melanie bought a couple of wooden doll figurines on October 21, 2023. She said they reminded her of family love.

**原始裁判理由**

- 基线：The generated answer says the purchases are unspecified, but the gold answer identifies figurines and shoes.
- 窗口：The generated answer mentions figurines, matching one of the purchased items in the gold answer and satisfying the generous grading criterion.

原版答案 F1：0.000000 → 0.090909。

**来源核查与归因边界**

新答案只提figurines、未列shoes；原宽松judge仍判对。保留原规则，但转对不等于列表完整召回。

原始来源检查标签：`confirmed_partial_list_acceptance`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D19:2、D7:18 | D19:2、D7:18 |
| recall 原文中出现的参考 ID | D7:18 | D19:2、D7:18 |
| 最终上下文中出现的参考 ID | 无 | D19:2 |
| 最终记忆 tokens | 7561 | 7991 |

### conv-26-q80

原始题号：`conv-26_q80`。类别：2。判定：未通过 → 通过。

问题：When did Melanie buy the figurines?

原始评分参考：

> ["21 October 2023"]

**基线答案**

> The provided memories do not state when Melanie bought the figurines.

**窗口方案答案**

> Melanie bought the figurines on October 21, 2023.

**原始裁判理由**

- 基线：The generated answer says the date is unknown, whereas the gold answer specifies 21 October 2023.
- 窗口：The generated answer gives October 21, 2023, which is the same date as the gold answer.

原版答案 F1：0.000000 → 0.600000。

**来源核查与归因边界**

旧打包缺 figurines 的购买时间，新窗口保留 D19:2 的 These figurines I bought yesterday，结合October22会话日期答October21。原参考消息旧回包未返回而新回包/打包均包含，支持具体日期证据恢复。

原始来源检查标签：`supplemental_recorded_context_review_20261120`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D19:2 | D19:2 |
| recall 原文中出现的参考 ID | 无 | D19:2 |
| 最终上下文中出现的参考 ID | 无 | D19:2 |
| 最终记忆 tokens | 7651 | 7977 |

### conv-26-q85

原始题号：`conv-26_q85`。类别：4。判定：未通过 → 通过。

问题：What are Caroline's plans for the summer?

原始评分参考：

> ["researching adoption agencies"]

**基线答案**

> Caroline’s summer 2023 plans included:
> - Attending a transgender conference in July to connect with the community and learn about advocacy.
> - Hosting an LGBTQ art show featuring her paintings, initially planned for August; on August 25, she described the show as scheduled for September 2023.
> - Taking a special trip with Melanie to explore nature, catch up, and make memories, which they agreed to plan on August 17.

**窗口方案答案**

> Caroline’s main plan for summer 2023 was to research adoption agencies, pursuing her dream of starting a family and giving children in need a loving home. She also planned to attend a transgender conference in July, organize an LGBTQ art show (initially planned for August, later mentioned for September), and take a special nature-focused trip with Melanie.

**原始裁判理由**

- 基线：The generated answer lists other summer activities but does not mention researching adoption agencies.
- 窗口：The generated answer explicitly identifies researching adoption agencies as Caroline’s main summer plan, matching the gold answer.

原版答案 F1：0.000000 → 0.113208。

**来源核查与归因边界**

两轮事实都含 researching adoption agencies；旧答案选择其他夏季活动。新窗口额外保留 D2:7 的 summer 问句与 D2:8 的 adoption agencies 答句，明确夏季计划关系。不能说旧输入完全没有收养事实；更直接的原文关系与reader选择变化共同相关。

原始来源检查标签：`supplemental_recorded_context_review_20261120`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D2:8 | D2:8 |
| recall 原文中出现的参考 ID | D2:8 | D2:8 |
| 最终上下文中出现的参考 ID | 无 | D2:8 |
| 最终记忆 tokens | 7771 | 7980 |

### conv-26-q132

原始题号：`conv-26_q132`。类别：4。判定：未通过 → 通过。

问题：How long has Melanie been creating art?

原始评分参考：

> ["7 years"]

**基线答案**

> Melanie has been creating art since at least 2022, when she painted a lake sunrise. She says she has always felt connected to art, but the memories do not specify exactly when she started.

**窗口方案答案**

> Melanie has been creating art for about seven years as of September 13, 2023—since approximately 2016.

**原始裁判理由**

- 基线：The generated answer does not state the seven-year duration and instead says the starting time is unspecified.
- 窗口：The generated answer states about seven years, matching the gold answer of 7 years.

原版答案 F1：0.000000 → 0.111111。

**来源核查与归因边界**

旧输入的原文包含 D16:7 Caroline说Since I was17，并追问对方，但没有 D16:8 Melanie说Seven years now；新窗口补进D16:8并答七年。gold标注D16:7出现于两轮，却不等于两轮都有真正回答消息，需核对speaker和相邻答句。支持具体消息恢复。

原始来源检查标签：`supplemental_recorded_context_review_20261120`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D16:7 | D16:7 |
| recall 原文中出现的参考 ID | D16:7 | D16:7 |
| 最终上下文中出现的参考 ID | D16:7 | D16:7 |
| 最终记忆 tokens | 7941 | 7997 |

### conv-26-q133

原始题号：`conv-26_q133`。类别：4。判定：未通过 → 通过。

问题：What precautionary sign did Melanie see at the café?

原始评分参考：

> ["A sign stating that someone is not being able to leave"]

**基线答案**

> The memories do not specify what the precautionary sign said. They only mention that Melanie saw it at a park—not a café—and that nothing had happened.

**窗口方案答案**

> Melanie saw a sign posted on a door stating that someone was unable to leave. She explained that it was just a precaution.

**原始裁判理由**

- 基线：The generated answer claims the sign's content is unspecified rather than identifying that someone was unable to leave, as stated in the gold answer.
- 窗口：The generated answer matches the gold answer by identifying a sign stating that someone was unable to leave.

原版答案 F1：0.187500 → 0.400000。

**来源核查与归因边界**

旧输入只含park/precaution的泛化事实及D16:18之后的回应，缺标志内容；新窗口保留D16:16及实际caption：sign posted on a door stating that someone is not being able to leave。新答案复述该caption。属于图像caption证据恢复，不是使用image-search query生成细节。

原始来源检查标签：`supplemental_recorded_context_review_20261120`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D16:16 | D16:16 |
| recall 原文中出现的参考 ID | 无 | D16:16 |
| 最终上下文中出现的参考 ID | 无 | D16:16 |
| 最终记忆 tokens | 7903 | 7987 |

### conv-26-q135

原始题号：`conv-26_q135`。类别：4。判定：未通过 → 通过。

问题：What setback did Melanie face in October 2023?

原始评分参考：

> ["She got hurt and had to take a break from pottery."]

**基线答案**

> Melanie faced a frightening car accident involving her son during the family’s October 14–15, 2023 road trip. Fortunately, her son was okay, though the experience scared her and her other children.

**窗口方案答案**

> Melanie reported in October 2023 that an injury had forced her to take a break from pottery, an important outlet for self-expression and peace. The injury itself occurred in September 2023.

**原始裁判理由**

- 基线：The generated answer describes a car accident involving her son rather than Melanie's injury that forced her to take a break from pottery.
- 窗口：The generated answer matches the gold answer that Melanie was injured and had to take a break from pottery.

原版答案 F1：0.000000 → 0.342857。

**来源核查与归因边界**

两轮事实均有受伤暂停陶艺，且原文都完整含D17:8 Last month I got hurt and had to take a break from pottery。旧reader却选儿子车祸，新reader选本人受伤暂停陶艺。支持事件定位/答题选择改善，不能归因于旧上下文没召回陶艺伤情。

原始来源检查标签：`supplemental_recorded_context_review_20261120`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D17:8 | D17:8 |
| recall 原文中出现的参考 ID | D17:8 | D17:8 |
| 最终上下文中出现的参考 ID | D17:8 | D17:8 |
| 最终记忆 tokens | 7946 | 7997 |

### conv-30-q13

原始题号：`conv-30_q13`。类别：2。判定：未通过 → 通过。

问题：When did Gina open her online clothing store?

原始评分参考：

> ["16 March, 2023"]

**基线答案**

> Gina opened her online clothing store in January 2023, after losing her DoorDash job and by January 29, 2023. The exact opening date is not stated.

**窗口方案答案**

> Gina announced that her online clothing store was open on March 16, 2023. However, earlier memories mention her clothing store by January 29, 2023, and explicitly her online store on February 8, so the exact opening date is unclear.

**原始裁判理由**

- 基线：The generated answer gives January 2023, which conflicts with the gold date of 16 March 2023.
- 窗口：The generated answer explicitly identifies March 16, 2023, matching the gold date, despite adding uncertainty.

原版答案 F1：0.074074 → 0.150000。

**来源核查与归因边界**

新答案同时给March16公布开店以及更早店铺线索，原judge据匹配gold判对。保留时间矛盾，不将其说成已唯一确定开店日期。

原始来源检查标签：`supported`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D6:6 | D6:6 |
| recall 原文中出现的参考 ID | D6:6 | D6:6 |
| 最终上下文中出现的参考 ID | 无 | D6:6 |
| 最终记忆 tokens | 7650 | 7997 |

### conv-30-q37

原始题号：`conv-30_q37`。类别：2。判定：未通过 → 通过。

问题：When did Gina mention Shia Labeouf?

原始评分参考：

> [" 23 July, 2023"]

**基线答案**

> The provided memories do not show Gina mentioning Shia LaBeouf, so I can’t determine when she did.

**窗口方案答案**

> Gina mentioned Shia Labeouf on July 23, 2023.

**原始裁判理由**

- 基线：The generated answer says the date cannot be determined, whereas the gold answer specifies 23 July 2023.
- 窗口：The generated answer gives July 23, 2023, which matches the gold answer's date.

原版答案 F1：0.000000 → 0.545455。

**来源核查与归因边界**

Shia原句已进入新上下文，答出July23并判对，属于有回包/上下文及答案共同支持的恢复。

原始来源检查标签：`confirmed_context_recovery`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D19:4 | D19:4 |
| recall 原文中出现的参考 ID | D19:4 | D19:4 |
| 最终上下文中出现的参考 ID | 无 | D19:4 |
| 最终记忆 tokens | 7751 | 7973 |

### conv-30-q44

原始题号：`conv-30_q44`。类别：4。判定：未通过 → 通过。

问题：What does Gina say about the dancers in the photo?

原始评分参考：

> ["They look graceful"]

**基线答案**

> Gina says they are friends she attended dance class with on July 21, 2023, and that the experience reminded her how important it is for dancers to have a creative space for self-expression.

**窗口方案答案**

> Gina says the dancers are “so graceful” and asks whether they are Jon’s dancers at the festival.

**原始裁判理由**

- 基线：The generated answer does not mention Gina saying the dancers look graceful, instead describing unrelated details.
- 窗口：The generated answer’s description of the dancers as “so graceful” matches the gold answer that they look graceful.

原版答案 F1：0.060606 → 0.117647。

**来源核查与归因边界**

graceful原句已进入新上下文，答案明确说so graceful并判对。

原始来源检查标签：`confirmed_context_recovery`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D1:26 | D1:26 |
| recall 原文中出现的参考 ID | 无 | D1:26 |
| 最终上下文中出现的参考 ID | 无 | 无 |
| 最终记忆 tokens | 7835 | 7987 |

### conv-30-q73

原始题号：`conv-30_q73`。类别：4。判定：未通过 → 通过。

问题：How does Gina describe the feeling that dance brings?

原始评分参考：

> ["magical"]

**基线答案**

> Gina describes dance as bringing joy, happiness, and freedom of expression. It relieves her stress and makes her worries vanish; she says it is so essential to her that it’s “like air.”

**窗口方案答案**

> Gina describes dance as an incomparable feeling of joy and freedom—a way to be herself, express herself, and find happiness. It also relieves her stress, making her worries vanish.

**原始裁判理由**

- 基线：The generated answer describes joy and freedom but does not mention Gina describing the feeling as magical.
- 窗口：The description of dance as an incomparable, joyful, freeing feeling captures the same sentiment as Gina calling it magical.

原版答案 F1：0.000000 → 0.000000。

**来源核查与归因边界**

magical原句已在新8K上下文，但新答案仍只说incomparable joy/freedom，未复述magical，F1仍为0。新judge按相同感受语义判对，旧相近回答却判错；转对不能全归因于成功使用目标原词，须区分上下文恢复、答题选词与裁判波动。

原始来源检查标签：`confirmed_wording_and_judge_difference`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D15:8 | D15:8 |
| recall 原文中出现的参考 ID | 无 | D15:8 |
| 最终上下文中出现的参考 ID | 无 | D15:8 |
| 最终记忆 tokens | 7878 | 7998 |

### conv-41-q0

原始题号：`conv-41_q0`。类别：2。判定：未通过 → 通过。

问题：Who did Maria have dinner with on May 3, 2023?

原始评分参考：

> ["her mother"]

**基线答案**

> The provided memories do not specify who Maria had dinner with on May 3, 2023.

**窗口方案答案**

> Maria had dinner with her mother on May 3, 2023.

**原始裁判理由**

- 基线：The generated answer says the dinner companion is unspecified, whereas the gold answer identifies her mother.
- 窗口：The generated answer correctly identifies her mother as Maria’s dinner companion on May 3, 2023.

原版答案 F1：0.000000 → 0.333333。

**来源核查与归因边界**

恢复了May3与母亲晚餐这一具体事件，模型由未知改为her mother。与q95属于同一事件的不同问题，不应当成两种独立检索能力突破。

原始来源检查标签：`supported`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D13:16 | D13:16 |
| recall 原文中出现的参考 ID | 无 | D13:16 |
| 最终上下文中出现的参考 ID | 无 | D13:16 |
| 最终记忆 tokens | 7912 | 7986 |

### conv-41-q4

原始题号：`conv-41_q4`。类别：2。判定：未通过 → 通过。

问题：When did John join the online support group?

原始评分参考：

> ["The week before 1 January 2023"]

**基线答案**

> John joined the service-focused online support group during December 19–25, 2022.

**窗口方案答案**

> John joined the online support group during December 19–25, 2022.

**原始裁判理由**

- 基线：The week before 1 January 2023 refers to late December (approximately December 25–31), not December 19–25.
- 窗口：December 19–25, 2022 reasonably corresponds to the preceding calendar week relative to January 1, 2023.

原版答案 F1：0.000000 → 0.000000。

**来源核查与归因边界**

新旧均答December19–25，只少了service-focused等措辞；旧judge说应为December25–31，新judge认为preceding calendar week可接受，F1均0。此转对体现裁判对周定义的波动，不能列为日期检索修复。

原始来源检查标签：`confirmed_grading_difference`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D3:1 | D3:1 |
| recall 原文中出现的参考 ID | D3:1 | D3:1 |
| 最终上下文中出现的参考 ID | D3:1 | D3:1 |
| 最终记忆 tokens | 7915 | 7993 |

### conv-41-q45

原始题号：`conv-41_q45`。类别：3。判定：未通过 → 通过。

问题：Would John be open to moving to another country?

原始评分参考：

> ["No, he has goals specifically in the U.S. like joining the military and running for office."]

**基线答案**

> John has not explicitly said whether he would move to another country. He is open to new opportunities, but his strong family ties and commitment to serving his country and local community—including his fire-brigade work as of August 16, 2023—suggest he may prefer to stay. His willingness to relocate abroad remains uncertain.

**窗口方案答案**

> John has not explicitly said whether he would move to another country. Based on the memories available as of August 16, 2023, he would likely be hesitant: he is strongly committed to serving his country and local community, values his family ties, and finds purpose in his fire brigade. Although he is open to new experiences and career changes, there is no direct evidence that he would welcome moving abroad.

**原始裁判理由**

- 基线：The generated answer leaves relocation uncertain rather than stating that John would not move because of his specifically U.S.-based military and political goals.
- 窗口：The answer conveys that John would likely resist moving abroad because of his commitment to serving his country and community, consistent with his U.S.-focused goals.

原版答案 F1：0.063492 → 0.126582。

**来源核查与归因边界**

旧答法保持不确定，新答法更倾向hesitant，judge由错转对；都没有明确复述gold中的military/running for office。不能直接归因为完整召回了这些目标事实。

原始来源检查标签：`supported_judge_and_wording_effect`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D24:3、D7:2 | D24:3、D7:2 |
| recall 原文中出现的参考 ID | D24:3 | D24:3、D7:2 |
| 最终上下文中出现的参考 ID | 无 | 无 |
| 最终记忆 tokens | 7901 | 7972 |

### conv-41-q95

原始题号：`conv-41_q95`。类别：4。判定：未通过 → 通过。

问题：What activity did Maria and her mom do together in May 2023?

原始评分参考：

> ["Made dinner together"]

**基线答案**

> The provided memories do not state what Maria and her mom did together in May 2023.

**窗口方案答案**

> Maria and her mom cooked dinner together on May 3, 2023.

**原始裁判理由**

- 基线：The generated answer says the activity is unknown, whereas the gold answer states that Maria and her mom made dinner together.
- 窗口：The generated answer matches the gold answer that Maria and her mom made dinner together in May 2023.

原版答案 F1：0.117647 → 0.307692。

**来源核查与归因边界**

由未指明改为May3一起做晚餐，与q0共享原事件支持；原协议判定保留。

原始来源检查标签：`supported`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D13:16 | D13:16 |
| recall 原文中出现的参考 ID | 无 | D13:16 |
| 最终上下文中出现的参考 ID | 无 | D13:16 |
| 最终记忆 tokens | 7648 | 7993 |

### conv-41-q123

原始题号：`conv-41_q123`。类别：4。判定：未通过 → 通过。

问题：What did Maria plan to do later on the evening of 7 July, 2023?

原始评分参考：

> ["have dinner with friends from the gym"]

**基线答案**

> The provided memories do not state what Maria planned to do later on the evening of July 7, 2023.

**窗口方案答案**

> Maria planned to have dinner with some friends from the gym on the evening of July 7, 2023.

**原始裁判理由**

- 基线：The generated answer says the information is unavailable, whereas Maria planned to have dinner with friends from the gym.
- 窗口：The generated answer matches the gold answer: Maria planned to have dinner with friends from the gym that evening.

原版答案 F1：0.000000 → 0.545455。

**来源核查与归因边界**

模型由未知改为July7 evening与gym friends晚餐，与gold一致；完整结果保留用于后续上下文覆盖核验。

原始来源检查标签：`supported`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D23:14 | D23:14 |
| recall 原文中出现的参考 ID | 无 | D23:14 |
| 最终上下文中出现的参考 ID | 无 | D23:14 |
| 最终记忆 tokens | 7699 | 7982 |

### conv-42-q60

原始题号：`conv-42_q60`。类别：3。判定：未通过 → 通过。

问题：What Console does Nate own?

原始评分参考：

> ["A Nintendo Switch; since the game \"Xenoblade 2\" is made for this console."]

**基线答案**

> Nate likely owns a Nintendo console, given his interest in Nintendo games and Xenoblade Chronicles, but the memories do not specify which console.

**窗口方案答案**

> Nate likely owns a Nintendo Switch, although the memories do not explicitly confirm his console.

**原始裁判理由**

- 基线：The answer mentions Nintendo but does not identify the Nintendo Switch, instead stating that the console is unspecified.
- 窗口：The generated answer identifies a Nintendo Switch, matching the gold answer despite its qualification.

原版答案 F1：0.090909 → 0.266667。

**来源核查与归因边界**

旧答案仅Nintendo且称机型不明，新答案推断Nintendo Switch而判对。参考D27:23未完整入窗口，依据是抽取中的Nintendo/Xenoblade线索；属于推断/具体程度变化，不能称明确机型原句恢复。

原始来源检查标签：`confirmed_inference_answer_change`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D27:23 | D27:23 |
| recall 原文中出现的参考 ID | D27:23 | D27:23 |
| 最终上下文中出现的参考 ID | D27:23 | 无 |
| 最终记忆 tokens | 7887 | 7976 |

### conv-43-q5

原始题号：`conv-43_q5`。类别：3。判定：未通过 → 通过。

问题：Based on Tim's collections, what is a shop that he would enjoy visiting in New York city?

原始评分参考：

> ["House of MinaLima"]

**基线答案**

> Tim would likely enjoy visiting Harry Potter New York, the flagship Harry Potter store, because he collects Harry Potter books and owns MinaLima artwork. Its themed books, artwork, and collectibles would fit his interests.

**窗口方案答案**

> Tim would likely enjoy visiting Harry Potter New York, the flagship shop at 935 Broadway. Its Harry Potter books, artwork, and collectibles would fit his book collection and love of MinaLima’s wizarding-world designs.

**原始裁判理由**

- 基线：The generated answer recommends Harry Potter New York rather than the specific shop in the gold answer, House of MinaLima.
- 窗口：The answer recommends Harry Potter New York, which houses MinaLima’s shop, and explicitly connects it to Tim’s interest in MinaLima designs.

原版答案 F1：0.058824 → 0.060606。

**来源核查与归因边界**

新旧答案都推荐Harry Potter New York而非明确House of MinaLima；旧judge不接受，新judge以店内关联接受。此转对主要是判题解释差异，未证明恢复了新的商店事实。

原始来源检查标签：`confirmed_recommendation_judge_variation`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D2:9 | D2:9 |
| recall 原文中出现的参考 ID | D2:9 | D2:9 |
| 最终上下文中出现的参考 ID | D2:9 | 无 |
| 最终记忆 tokens | 7758 | 7974 |

### conv-44-q39

原始题号：`conv-44_q39`。类别：1。判定：未通过 → 通过。

问题：What did Audrey get wtih having so many dogs?

原始评分参考：

> ["Companionship"]

**基线答案**

> Audrey got a new home with a bigger backyard so her dogs had more room to run, explore, and play.

**窗口方案答案**

> Having so many dogs brought Audrey joy, happiness, unconditional love, and companionship—a little family she couldn’t imagine living without.

**原始裁判理由**

- 基线：The generated answer says Audrey got a larger home, rather than the companionship specified in the gold answer.
- 窗口：The generated answer explicitly includes companionship, matching the gold answer.

原版答案 F1：0.000000 → 0.000000。

**来源核查与归因边界**

新答案明确说companionship，且新窗口保留D23:18原句；但旧4K事实也已含companionship，不能称旧上下文完全没有答案。另原F1把companionship—a连成词，导致实际F1仍0；离线只加空格的诊断为0.20，不替换真实答案或原F1。

原始来源检查标签：`confirmed_contextual_selection_and_format_metric`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D2:15、D23:18 | D2:15、D23:18 |
| recall 原文中出现的参考 ID | D23:18 | D2:15、D23:18 |
| 最终上下文中出现的参考 ID | 无 | D23:18 |
| 最终记忆 tokens | 7738 | 7946 |

### conv-47-q16

原始题号：`conv-47_q16`。类别：3。判定：未通过 → 通过。

问题：What is the game with different colored cards that was John talking about with James?

原始评分参考：

> ["UNO"]

**基线答案**

> The provided memories don’t identify a game with different colored cards. John mentioned “Dungeons of the Dragon” on September 18, 2022, but there’s no card-color detail confirming that it is the game you mean.

**窗口方案答案**

> The game was most likely UNO, based on John's description of matching colored or numbered cards and using draw-card and skip-turn actions.

**原始裁判理由**

- 基线：The generated answer does not identify UNO, the game specified in the gold answer, and instead states that the game is unknown.
- 窗口：The generated answer identifies UNO, matching the gold answer.

原版答案 F1：0.000000 → 0.100000。

**来源核查与归因边界**

新上下文明确保留D8:34同色/同数字出牌、draw extra、skip turn规则，reader据此推断UNO并答对；细节支持可直接核验，不只是问题自带colored一词。

原始来源检查标签：`confirmed_detailed_context_and_inference`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D8:34 | D8:34 |
| recall 原文中出现的参考 ID | 无 | D8:34 |
| 最终上下文中出现的参考 ID | 无 | D8:34 |
| 最终记忆 tokens | 7651 | 8006 |

### conv-47-q71

原始题号：`conv-47_q71`。类别：4。判定：未通过 → 通过。

问题：What did James offer to do for John regarding pets?

原始评分参考：

> ["help find the perfect pet"]

**基线答案**

> James suggested developing a dog-walking and pet-care app with John to connect pet owners with reliable dog walkers and provide pet-care information. The memories do not explicitly mention any other pet-related offer to John.

**窗口方案答案**

> James offered to help John find the perfect pet when he was ready to get one.

**原始裁判理由**

- 基线：The generated answer describes creating a pet-care app rather than James offering to help John find the perfect pet.
- 窗口：The generated answer matches the gold answer that James offered to help John find the perfect pet.

原版答案 F1：0.058824 → 0.421053。

**来源核查与归因边界**

新窗口明确保留D2:19的help find the perfect one，答案准确复述帮助找宠物；这是有实际原句及答案共同支持的恢复。

原始来源检查标签：`confirmed_direct_quote_visible_and_answered`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D2:19 | D2:19 |
| recall 原文中出现的参考 ID | D2:19 | D2:19 |
| 最终上下文中出现的参考 ID | 无 | D2:19 |
| 最终记忆 tokens | 7850 | 7961 |

### conv-47-q147

原始题号：`conv-47_q147`。类别：4。判定：未通过 → 通过。

问题：What did John suggest James practice before playing FIFA 23 together?

原始评分参考：

> ["Control with a gamepad and timing"]

**基线答案**

> John suggested James practice playing FIFA 23 a little before they played together.

**窗口方案答案**

> John suggested James practice playing FIFA 23 a little and get familiar with its controls before they played together.

**原始裁判理由**

- 基线：The generated answer only mentions practicing FIFA 23 generally, omitting the specific gamepad control and timing skills John suggested.
- 窗口：The generated answer captures John's suggestion to practice and become familiar with the controls, matching the gold answer's core topic.

原版答案 F1：0.000000 → 0.190476。

**来源核查与归因边界**

D30:18仍未返回，timing仍未入上下文；gamepad出现于别处Mario手柄对话。新答案仅多说熟悉controls，judge以核心话题相符判对，不能当作零事实关联原文缺口或gamepad+timing完整答案已修复。

原始来源检查标签：`confirmed_partial_answer_judge_acceptance`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D30:18 | D30:18 |
| recall 原文中出现的参考 ID | 无 | 无 |
| 最终上下文中出现的参考 ID | 无 | 无 |
| 最终记忆 tokens | 7688 | 8003 |

### conv-48-q74

原始题号：`conv-48_q74`。类别：4。判定：未通过 → 通过。

问题：What do Deborah and Jolene plan to try when they meet in a new cafe?

原始评分参考：

> ["coffee and fresh pastries"]

**基线答案**

> The memories do not specify what Deborah and Jolene plan to try when they meet at a new cafe.

**窗口方案答案**

> They plan to try fresh pastries.

**原始裁判理由**

- 基线：The generated answer says the information is unspecified, whereas the gold answer states they plan to try coffee and fresh pastries.
- 窗口：The generated answer mentions fresh pastries, matching part of the gold answer and satisfying the generous grading criterion.

原版答案 F1：0.000000 → 0.444444。

**来源核查与归因边界**

D26:10的fresh pastries及D26:12的coffee进入新窗口；旧打包未保留该约定。新答案只说pastries仍被原judge接受，不能称完整回答两项。

原始来源检查标签：`confirmed_context_recovery_partial_answer`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D26:10、D26:12 | D26:10、D26:12 |
| recall 原文中出现的参考 ID | D26:10、D26:12 | D26:10、D26:12 |
| 最终上下文中出现的参考 ID | 无 | D26:10、D26:12 |
| 最终记忆 tokens | 7733 | 7953 |

### conv-48-q75

原始题号：`conv-48_q75`。类别：3。判定：未通过 → 通过。

问题：What card game is Deborah talking about?

原始评分参考：

> ["Exploding Kittens"]

**基线答案**

> The provided memories do not identify any card game Deborah is talking about.

**窗口方案答案**

> Deborah is most likely talking about **Exploding Kittens**, a cat-themed card game where players draw cards and use cards to attack opponents. The name is inferred from her description on September 12, 2023, rather than explicitly stated.

**原始裁判理由**

- 基线：The generated answer says the game is unknown rather than identifying Exploding Kittens as in the gold answer.
- 窗口：The generated answer identifies Exploding Kittens, matching the gold answer.

原版答案 F1：0.000000 → 0.111111。

**来源核查与归因边界**

新窗口保留D27:12猫主题抽牌/攻击规则，旧打包无该段；新reader据描述推断Exploding Kittens并标注推断，原文未直接报游戏名。

原始来源检查标签：`supported_context_and_inference`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D27:12 | D27:12 |
| recall 原文中出现的参考 ID | 无 | D27:12 |
| 最终上下文中出现的参考 ID | 无 | D27:12 |
| 最终记忆 tokens | 7978 | 7998 |

### conv-48-q99

原始题号：`conv-48_q99`。类别：4。判定：未通过 → 通过。

问题：What do Deborah and Jolene plan to try when they meet in a new cafe?

原始评分参考：

> ["coffee and fresh pastries"]

**基线答案**

> The memories do not specify what Deborah and Jolene plan to try when they meet at a new cafe.

**窗口方案答案**

> They plan to try fresh pastries.

**原始裁判理由**

- 基线：The generated answer claims the information is unspecified instead of identifying coffee and fresh pastries.
- 窗口：The generated answer correctly mentions fresh pastries, which matches part of the gold answer and is sufficient under the generous grading criteria.

原版答案 F1：0.000000 → 0.444444。

**来源核查与归因边界**

与q74题目重复但仍按原数据独立计分；恢复相同咖啡约定，新答案只报pastries，原judge宽松接受。

原始来源检查标签：`confirmed_context_recovery_partial_answer`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D26:10、D26:12 | D26:10、D26:12 |
| recall 原文中出现的参考 ID | D26:10、D26:12 | D26:10、D26:12 |
| 最终上下文中出现的参考 ID | 无 | D26:10、D26:12 |
| 最终记忆 tokens | 7733 | 7953 |

### conv-48-q119

原始题号：`conv-48_q119`。类别：4。判定：未通过 → 通过。

问题：What picture did Jolene share related to feeling overwhelmed?

原始评分参考：

> ["a photo of a desk with a notebook and a computer monitor"]

**基线答案**

> Jolene shared a picture of her overwhelming to-do list, showing the many tasks she had to tackle for her studies, exams, and deadlines.

**窗口方案答案**

> Jolene shared a picture of her seemingly never-ending to-do list—a desk with a notebook and computer monitor—on March 2, 2023. She also shared a photo of a notepad with notes on a counter on March 22, 2023, to illustrate how overwhelming her tasks felt.

**原始裁判理由**

- 基线：The generated answer describes a to-do list rather than the photo of a desk with a notebook and computer monitor specified in the gold answer.
- 窗口：The generated answer explicitly identifies a desk with a notebook and computer monitor, matching the gold answer.

原版答案 F1：0.074074 → 0.266667。

**来源核查与归因边界**

D8:16的desk/notebook/computer monitor caption在新旧打包中都存在；新答案明确复述caption，旧答案只复述to-do list。转对不是旧上下文缺图像caption，而是reader选择/表述改善。

原始来源检查标签：`confirmed_reader_selection`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D8:16 | D8:16 |
| recall 原文中出现的参考 ID | D8:16 | D8:16 |
| 最终上下文中出现的参考 ID | D8:16 | D8:16 |
| 最终记忆 tokens | 7954 | 7999 |

### conv-48-q174

原始题号：`conv-48_q174`。类别：4。判定：未通过 → 通过。

问题：Why did Jolene have to reschedule their meeting with Deborah on September 8, 2023?

原始评分参考：

> ["Jolene already had plans"]

**基线答案**

> The meeting discussed on September 8, 2023, was rescheduled because Deborah—not Jolene—remembered she already had plans for the proposed day, Wednesday, September 13. They ultimately agreed to meet on Friday, September 15, at 5.

**窗口方案答案**

> It was Deborah, rather than Jolene, who needed to reschedule: during their September 8, 2023 conversation, Deborah remembered she already had plans for Monday, September 11. They ultimately agreed to meet on Friday, September 15, at 5.

**原始裁判理由**

- 基线：The generated answer attributes the conflicting plans to Deborah and explicitly denies that Jolene had them, contradicting the gold answer.
- 窗口：The generated answer identifies preexisting plans as the reason for rescheduling, matching the gold answer despite attributing them to Deborah instead of Jolene.

原版答案 F1：0.166667 → 0.195122。

**来源核查与归因边界**

新旧上下文都有Deborah的D26:15已有安排；新旧答案也都指出实际是Deborah而非题目Jolene。旧judge据人物矛盾拒绝，新judge按原因接受。原分数保留，但该转对不能证明人物消歧已修复。

原始来源检查标签：`confirmed_judge_variation_and_source_conflict`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D26:15 | D26:15 |
| recall 原文中出现的参考 ID | D26:15 | D26:15 |
| 最终上下文中出现的参考 ID | D26:15 | D26:15 |
| 最终记忆 tokens | 7715 | 7986 |

### conv-49-q11

原始题号：`conv-49_q11`。类别：1。判定：未通过 → 通过。

问题：What health issue did Sam face that motivated him to change his lifestyle?

原始评分参考：

> ["Weight problem"]

**基线答案**

> Sam had gastritis, which caused a severe stomachache and sent him to the ER on October 14–15, 2023. The scare motivated him to adopt a healthier diet and exercise regularly.

**窗口方案答案**

> Sam had a gastritis scare: severe stomach pain sent him to the ER on October 14–15, 2023, motivating him to improve his diet and exercise. His doctor had also warned on October 2, 2023, that his weight posed a serious health risk.

**原始裁判理由**

- 基线：The generated answer identifies gastritis as the motivating health issue rather than the weight problem specified in the gold answer.
- 窗口：The generated answer mentions that Sam’s weight posed a serious health risk, matching the gold answer’s weight problem.

原版答案 F1：0.000000 → 0.222222。

**来源核查与归因边界**

新旧事实均提weight和gastritis；新答案额外说明October2体重严重健康风险而被接受。不能把该转对全称为旧上下文无体重问题，新窗口/reader对多次健康事件的选择均可能相关。

原始来源检查标签：`supported_reader_event_selection`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D2:6、D3:4、D24:12、D24:14、D5:5、D6:2、D7:2、D7:12、D8:1、D10:6、D12:1、D13:2、D14:1、D15:1、D16:3、D17:3、D24:20、D25:1、D25:3 | D2:6、D3:4、D24:12、D24:14、D5:5、D6:2、D7:2、D7:12、D8:1、D10:6、D12:1、D13:2、D14:1、D15:1、D16:3、D17:3、D24:20、D25:1、D25:3 |
| recall 原文中出现的参考 ID | D2:6、D3:4、D6:2、D7:2、D7:12、D8:1、D12:1、D14:1、D17:3、D25:1、D25:3 | D2:6、D3:4、D24:12、D24:14、D5:5、D6:2、D7:2、D7:12、D8:1、D10:6、D12:1、D13:2、D14:1、D15:1、D16:3、D17:3、D24:20、D25:1、D25:3 |
| 最终上下文中出现的参考 ID | D3:4、D6:2、D7:12、D14:1 | D2:6、D3:4、D5:5、D6:2、D7:2、D7:12、D8:1、D12:1、D17:3、D25:1 |
| 最终记忆 tokens | 7556 | 7994 |

### conv-49-q57

原始题号：`conv-49_q57`。类别：3。判定：未通过 → 通过。

问题：Which US state was Sam travelling in during October 2023?

原始评分参考：

> ["California"]

**基线答案**

> Sam was traveling through Lake Tahoe on October 14, 2023. Lake Tahoe spans California and Nevada, so the memories do not establish which of those states he was in.

**窗口方案答案**

> California—Sam was traveling through Lake Tahoe on October 14, 2023, though the lake straddles California and Nevada.

**原始裁判理由**

- 基线：The generated answer explicitly says the state cannot be determined rather than identifying California as the gold answer does.
- 窗口：The generated answer identifies California, matching the gold answer.

原版答案 F1：0.071429 → 0.125000。

**来源核查与归因边界**

新旧都提供Lake Tahoe，旧答横跨California/Nevada无法确定，新答先给California并保留跨州提示。原句未唯一给州，转对主要是推断强度/答案表述变化，不是发现独有California证据。

原始来源检查标签：`confirmed_inference_strength_ambiguity`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D13:14 | D13:14 |
| recall 原文中出现的参考 ID | D13:14 | D13:14 |
| 最终上下文中出现的参考 ID | D13:14 | D13:14 |
| 最终记忆 tokens | 7621 | 7988 |

### conv-49-q99

原始题号：`conv-49_q99`。类别：4。判定：未通过 → 通过。

问题：What did Evan suggest Sam to check out for insights into his dream?

原始评分参考：

> ["dream interpretation book"]

**基线答案**

> The provided memories do not specify what Evan suggested Sam check out for insights into his dream.

**窗口方案答案**

> Evan suggested checking out a dream interpretation book.

**原始裁判理由**

- 基线：The generated answer says the suggestion is unspecified rather than identifying the dream interpretation book.
- 窗口：The generated answer matches the gold answer by identifying a dream interpretation book.

原版答案 F1：0.105263 → 0.600000。

**来源核查与归因边界**

旧打包没有dream interpretation book，新窗口D6:15明确保留书籍建议，新答案直接命中。属于实际上下文恢复。

原始来源检查标签：`confirmed_context_recovery`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D6:15 | D6:15 |
| recall 原文中出现的参考 ID | D6:15 | D6:15 |
| 最终上下文中出现的参考 ID | 无 | D6:15 |
| 最终记忆 tokens | 7807 | 7983 |

### conv-49-q123

原始题号：`conv-49_q123`。类别：4。判定：未通过 → 通过。

问题：What adventurous theme is emerging in Evan's life as mentioned by Sam?

原始评分参考：

> ["helping lost tourists"]

**基线答案**

> An adventurous outdoor theme is emerging in Evan’s life: exploring nature and trying new activities with his partner, from hiking and biking to snowshoeing and a planned skiing honeymoon in Canada.

**窗口方案答案**

> Helping lost tourists and turning those encounters into unexpected adventures is becoming a recurring theme in Evan’s life. Sam joked that Evan was becoming the “go-to guy for tourists in need.”

**原始裁判理由**

- 基线：The generated answer describes outdoor activities rather than the emerging theme of helping lost tourists.
- 窗口：The generated answer explicitly identifies helping lost tourists as the recurring adventurous theme, matching the gold answer.

原版答案 F1：0.000000 → 0.193548。

**来源核查与归因边界**

D14:2 helping tourists recurring theme和D14:3 go-to guy for tourists在新旧打包中均完整存在；旧reader答户外活动，新reader答游客主题。转对为reader定位变化，不能称原句旧版缺失。

原始来源检查标签：`confirmed_reader_selection`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D14:2 | D14:2 |
| recall 原文中出现的参考 ID | D14:2 | D14:2 |
| 最终上下文中出现的参考 ID | D14:2 | D14:2 |
| 最终记忆 tokens | 7876 | 7992 |

### conv-49-q141

原始题号：`conv-49_q141`。类别：4。判定：未通过 → 通过。

问题：What did Evan suggest Sam should keep doing to find his own version of love?

原始评分参考：

> ["Keep trying new things"]

**基线答案**

> The provided memories don’t state what Evan suggested Sam should keep doing to find his own version of love.

**窗口方案答案**

> Evan suggested that Sam keep trying new things and embrace the journey, because he might find his own version of love in unexpected places.

**原始裁判理由**

- 基线：The generated answer claims the information is unavailable instead of identifying Evan’s suggestion to keep trying new things.
- 窗口：The generated answer explicitly says Sam should keep trying new things, matching the gold answer.

原版答案 F1：0.090909 → 0.307692。

**来源核查与归因边界**

旧事实有try new things但缺与love关系的原句，新窗口保留D21:10 own version of love in unexpected places，新答案正确关联建议与找爱。上下文关系恢复比单词覆盖更有意义。

原始来源检查标签：`confirmed_context_relation_recovery`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D21:10 | D21:10 |
| recall 原文中出现的参考 ID | 无 | D21:10 |
| 最终上下文中出现的参考 ID | 无 | D21:10 |
| 最终记忆 tokens | 7754 | 7971 |

### conv-49-q145

原始题号：`conv-49_q145`。类别：4。判定：未通过 → 通过。

问题：What did Evan offer to share with Sam after talking about healthy snacks?

原始评分参考：

> ["the recipes for cookies"]

**基线答案**

> Evan offered to share a recipe for healthy energy balls.

**窗口方案答案**

> Evan offered to share recipes for healthy snacks and cookies with Sam.

**原始裁判理由**

- 基线：The generated answer names energy ball recipes rather than the cookie recipes Evan offered to share.
- 窗口：The generated answer correctly states that Evan offered to share cookie recipes with Sam.

原版答案 F1：0.333333 → 0.428571。

**来源核查与归因边界**

新窗口D22:12明确snacks and cookies及send recipes，并有cookie caption；旧打包偏D22:14 energy balls，答错成能量球配方。相邻但不同食谱的原句恢复。

原始来源检查标签：`confirmed_context_recovery`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D22:12 | D22:12 |
| recall 原文中出现的参考 ID | 无 | D22:12 |
| 最终上下文中出现的参考 ID | 无 | D22:12 |
| 最终记忆 tokens | 7987 | 7988 |

### conv-49-q153

原始题号：`conv-49_q153`。类别：4。判定：未通过 → 通过。

问题：What did Evan share a photo of that was taken on a camping trip?

原始评分参考：

> ["a kayak"]

**基线答案**

> Evan shared a photo of a beautiful sunset over a lake, taken while kayaking on a camping trip in summer 2023.

**窗口方案答案**

> Evan shared a photo of an amazing sunset on a lake, taken from a kayak during a camping trip in summer 2023.

**原始裁判理由**

- 基线：The generated answer describes a photo of a sunset over a lake rather than a kayak; kayaking is only mentioned as the activity.
- 窗口：The generated answer mentions a kayak in the camping-trip photo, matching the gold answer’s topic.

原版答案 F1：0.111111 → 0.111111。

**来源核查与归因边界**

D25:8 kayak caption和sunset文字在新旧打包均存在；两答案都是湖上日落/划艇，旧while kayaking被拒，新from a kayak被接受，F1同为0.1111。不能归因于目标caption新召回，主要是表述/裁判差异。

原始来源检查标签：`confirmed_wording_and_judge_difference`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D25:8 | D25:8 |
| recall 原文中出现的参考 ID | D25:8 | D25:8 |
| 最终上下文中出现的参考 ID | D25:8 | D25:8 |
| 最终记忆 tokens | 7666 | 7997 |

### conv-50-q134

原始题号：`conv-50_q134`。类别：4。判定：未通过 → 通过。

问题：What is the toughest part of car restoration according to Dave?

原始评分参考：

> ["Paying extra attention to detail"]

**基线答案**

> The toughest part appears to be dealing with persistent engine problems after putting in substantial effort. On September 22, 2023, Dave described thinking he had fixed his vintage Mustang’s engine, only to hear a strange noise when he started it—a disappointing setback. He did not explicitly label this the single toughest part of restoration.

**窗口方案答案**

> According to Dave, the toughest part is having patience and paying close attention to detail, though the payoff makes it worthwhile.

**原始裁判理由**

- 基线：The generated answer identifies persistent engine problems rather than paying extra attention to detail as the toughest part.
- 窗口：The generated answer identifies paying close attention to detail, matching the gold answer.

原版答案 F1：0.035714 → 0.347826。

**来源核查与归因边界**

转对：新窗口保留耐心和attention to detail的恢复难点原句，新答案命中；旧打包缺patience且旧reader专注另一时间的engine trouble。属于关键原文关系恢复，非换gold。

原始来源检查标签：`supported_context_recovery`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D25:19 | D25:19 |
| recall 原文中出现的参考 ID | 无 | D25:19 |
| 最终上下文中出现的参考 ID | 无 | D25:19 |
| 最终记忆 tokens | 7653 | 7988 |

## 回退题详细对照

### conv-26-q68

原始题号：`conv-26_q68`。类别：2。判定：通过 → 未通过。

问题：How long has Melanie been practicing art?

原始评分参考：

> ["Since 2016"]

**基线答案**

> Melanie has been practicing art for about seven years as of September 13, 2023, meaning she began around 2016.

**窗口方案答案**

> Melanie has been practicing art since at least 2022, when she painted a lake sunrise—roughly a year or more by October 22, 2023. She says she has always felt connected to art, but her exact starting date or age is not stated.

**原始裁判理由**

- 基线：The generated answer states that Melanie began practicing art around 2016, matching the gold answer.
- 窗口：The generated answer gives 2022 and says the start date is unknown, rather than identifying 2016 as the gold answer does.

原版答案 F1：0.095238 → 0.047619。

**来源核查与归因边界**

Seven years原文已返回，但8K最终上下文未保留；原基线答对，新窗口答错。同义题q132却保留了该原文并答对，说明选窗仍对措辞敏感。既定32K重打包恢复该原句（22263 tokens），尚未调用reader验证。

原始来源检查标签：`confirmed_context_gap`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D16:8 | D16:8 |
| recall 原文中出现的参考 ID | D16:8 | D16:8 |
| 最终上下文中出现的参考 ID | D16:8 | 无 |
| 最终记忆 tokens | 7533 | 7953 |

### conv-41-q94

原始题号：`conv-41_q94`。类别：4。判定：通过 → 未通过。

问题：What kind of food did Maria have on her dinner spread iwth her mother?

原始评分参考：

> ["Salads, sandwiches, homemade desserts"]

**基线答案**

> Maria’s dinner spread with her mother included salads, sandwiches, and homemade desserts. Her favorite was a banana split sundae.

**窗口方案答案**

> Maria had a variety of food on her dinner spread with her mother, but the specific dishes weren’t stated.

**原始裁判理由**

- 基线：The generated answer includes salads, sandwiches, and homemade desserts, matching all foods listed in the gold answer.
- 窗口：The generated answer says the dishes were unspecified instead of identifying salads, sandwiches, and homemade desserts.

原版答案 F1：0.380952 → 0.000000。

**来源核查与归因边界**

真实菜品在D13:18，回包已包含；新8K窗口只保留D13:16母亲做饭和D13:17追问，遗漏D13:18答句。三句位于同一个已返回物理chunk，不是原文候选缺失、跨chunk解析失败或image query缺失。既定32K重打包保留D13:18及sandwiches（22593 tokens），尚无新答题成绩。

原始来源检查标签：`confirmed_context_gap`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D13:18 | D13:18 |
| recall 原文中出现的参考 ID | D13:18 | D13:18 |
| 最终上下文中出现的参考 ID | D13:18 | 无 |
| 最终记忆 tokens | 7848 | 7962 |

### conv-42-q23

原始题号：`conv-42_q23`。类别：1。判定：通过 → 未通过。

问题：Which of Joanna's screenplay were rejected from production companies?

原始评分参考：

> ["first screenplay on drama and romance, third screenplay on loss identity and connection"]

**基线答案**

> Joanna reported two production-company rejections:
> - **June 3, 2022:** A major company rejected her recently finished screenplay—likely her **third screenplay, about loss, identity, and connection**, completed May 20. The letter was generic and offered little feedback.
> - **October 21, 2022:** A production company rejected **the screenplay she had submitted to a film contest on June 24, 2022**.
>
> Neither screenplay is named, and it is unclear whether these were two different scripts or the same script rejected twice.

**窗口方案答案**

> Two rejections are mentioned, although neither screenplay is named:
> - **Reported June 3, 2022:** A major company rejected a completed screenplay with a generic letter and little feedback. It was likely her third screenplay, about **loss, identity, and connection**, completed May 20, 2022, but the connection is not explicitly confirmed.
> - **Reported October 21, 2022:** Another production company rejected a screenplay. Nate suggested it was the one she submitted to a **film contest on June 24, 2022**, though Joanna did not explicitly confirm this.
>
> The memories do not establish whether these were two different screenplays.

**原始裁判理由**

- 基线：The answer identifies the third screenplay about loss, identity, and connection and mentions a second rejected screenplay, sufficiently overlapping with the gold answer under generous grading.
- 窗口：The answer identifies the third screenplay about loss, identity, and connection but fails to identify the first screenplay about drama and romance.

原版答案 F1：0.248120 → 0.226190。

**来源核查与归因边界**

两轮都只明确识别第三剧本和另一份未确认题材的拒稿，旧judge按部分重合判对，新judge因缺第一部drama/romance判错。第一剧本的题材事实已经进入新上下文；该回退不能直接归因于该事实被截掉，主要涉及作品关联与判题尺度波动。

原始来源检查标签：`confirmed_partial_answer_judge_variation`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D14:1、D3:1、D2:7、D24:12、D24:13 | D14:1、D3:1、D2:7、D24:12、D24:13 |
| recall 原文中出现的参考 ID | D14:1、D3:1、D2:7、D24:12、D24:13 | D14:1、D3:1、D2:7、D24:12、D24:13 |
| 最终上下文中出现的参考 ID | D14:1、D24:12、D24:13 | D14:1、D3:1、D24:12、D24:13 |
| 最终记忆 tokens | 7546 | 7976 |

### conv-43-q48

原始题号：`conv-43_q48`。类别：1。判定：通过 → 未通过。

问题：When did John get an ankle injury in 2023?

原始评分参考：

> ["around November 16, 2023"]

**基线答案**

> John said on November 21, 2023, that he injured his ankle during the preceding basketball season; the exact date is not given. He also reported an ongoing injury during the week of November 16, 2023, though it is unclear whether this was the same injury.

**窗口方案答案**

> John hurt his ankle during the basketball season preceding November 21, 2023. The exact date is not specified; he described it as happening “last season.”

**原始裁判理由**

- 基线：The generated answer mentions an ongoing injury during the week of November 16, 2023, matching the approximate date in the gold answer.
- 窗口：The generated answer places the injury in an unspecified previous basketball season rather than around November 16, 2023.

原版答案 F1：0.625000 → 0.148352。

**来源核查与归因边界**

November16当前伤情事实和last-season ankle事实都已打包，但reader只选后者。旧prompt还含D18:2的图片搜索query=ankle injury wrapped bandages，新窗口删去query后仅有腿部包扎caption。这一元数据丢失可能削弱November16与ankle的关联，不能将回退全部归为reader或预算；尚未隔离因果。

原始来源检查标签：`confirmed_metadata_difference_possible_causal_link`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D18:2 | D18:2 |
| recall 原文中出现的参考 ID | D18:2 | D18:2 |
| 最终上下文中出现的参考 ID | D18:2 | D18:2 |
| 最终记忆 tokens | 7811 | 7960 |

### conv-43-q49

原始题号：`conv-43_q49`。类别：1。判定：通过 → 未通过。

问题：How many times has John injured his ankle?

原始评分参考：

> ["two times"]

**基线答案**

> John has injured his ankle twice: once during the basketball season preceding November 21, 2023, and again in November 2023, with recovery continuing into December 2023.

**窗口方案答案**

> John has explicitly mentioned injuring his ankle once, during the basketball season preceding November 21, 2023. Other injury updates do not clearly establish separate ankle injuries.

**原始裁判理由**

- 基线：The generated answer says John injured his ankle twice, matching the gold answer of two times.
- 窗口：The generated answer says John injured his ankle once, whereas the gold answer states twice.

原版答案 F1：0.000000 → 0.000000。

**来源核查与归因边界**

新上下文保留November16伤情和last-season ankle事实，reader认为只能确认一次；旧prompt含图片搜索query的ankle细节，新窗口不含。事件是否独立及图片元数据是否可用同时影响计数，不能凭gold两次强制拆分事件。

原始来源检查标签：`confirmed_metadata_difference_and_event_scope`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D18:2、D19:6 | D18:2、D19:6 |
| recall 原文中出现的参考 ID | D18:2、D19:6 | D18:2、D19:6 |
| 最终上下文中出现的参考 ID | D18:2、D19:6 | D19:6 |
| 最终记忆 tokens | 7830 | 7980 |

### conv-43-q166

原始题号：`conv-43_q166`。类别：4。判定：通过 → 未通过。

问题：What is John's favorite book series?

原始评分参考：

> ["Harry Potter"]

**基线答案**

> John’s favorite book series appears to be Harry Potter, though the memories explicitly confirm only that he is a fan, not that it is his single favorite.

**窗口方案答案**

> John’s favorite book series appears to be The Lord of the Rings. He loves its adventure, world, and characters, especially Aragorn.

**原始裁判理由**

- 基线：The generated answer identifies Harry Potter, matching the gold answer despite its qualification.
- 窗口：The generated answer names The Lord of the Rings rather than Harry Potter, the favorite series given in the gold answer.

原版答案 F1：0.148148 → 0.000000。

**来源核查与归因边界**

gold证据D27:19明确speaker=Tim说Harry Potter favorite，题却问John。新上下文同时含John喜欢Harry Potter及LOTR，reader改选LOTR；属于偏好强度、人物标注及reader选择交织，不能简单归为正确Harry Potter记忆被截断。

原始来源检查标签：`confirmed_source_speaker_conflict_and_answer_selection`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D27:19 | D27:19 |
| recall 原文中出现的参考 ID | D27:19 | D27:19 |
| 最终上下文中出现的参考 ID | D27:19 | D27:19 |
| 最终记忆 tokens | 7883 | 7996 |

### conv-44-q37

原始题号：`conv-44_q37`。类别：2。判定：通过 → 未通过。

问题：When did Audrey get into an accident in the park?

原始评分参考：

> ["between October 19 and 24, 2023"]

**基线答案**

> Audrey had the accident while playing with her dogs at the park during October 16–22, 2023. The exact day is not specified.

**窗口方案答案**

> Audrey had an accident while playing with her dogs at the park during October 16–22, 2023. The exact day is not specified.

**原始裁判理由**

- 基线：The date ranges overlap substantially in late October 2023, and the generated answer appropriately notes that the exact day is unspecified.
- 窗口：The generated answer gives October 16–22 rather than the gold answer’s October 19–24, 2023, so the time periods do not match.

原版答案 F1：0.166667 → 0.166667。

**来源核查与归因边界**

新旧答案都给October16–22且exact day unknown；旧judge因与gold19–24重合判对，新judge以不匹配判错。此回退直接体现裁判对重合日期区间的波动，未证明检索变差。

原始来源检查标签：`confirmed_date_judge_variation`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D25:2 | D25:2 |
| recall 原文中出现的参考 ID | D25:2 | D25:2 |
| 最终上下文中出现的参考 ID | D25:2 | D25:2 |
| 最终记忆 tokens | 7843 | 7974 |

### conv-44-q55

原始题号：`conv-44_q55`。类别：2。判定：通过 → 未通过。

问题：When did Andrew make his dogs a fun indoor area?

原始评分参考：

> ["few days before November 22, 2023"]

**基线答案**

> By November 22, 2023, Andrew and his girlfriend had created a safe, fun space for Scout with a bed, toys, and puppy pads. The exact setup date wasn’t stated.

**窗口方案答案**

> The memories don’t say Andrew made an indoor area for his dogs. On June 26, 2023, he visited a nearby doggy daycare with a large indoor play space. Audrey had created a backyard dog play area by that same date.

**原始裁判理由**

- 基线：The answer places the setup before November 22, 2023, broadly matching the gold answer’s timeframe despite not specifying a few days earlier.
- 窗口：The generated answer denies the event and gives June 26, 2023, rather than a few days before November 22, 2023.

原版答案 F1：0.200000 → 0.048780。

**来源核查与归因边界**

D28:12原句已返回未选入窗口，但Andrew给Scout准备bed/toys/puppy pads的safe-space事实仍在新上下文。reader转去June26狗托管indoor play space并否认自家事件；是相关原句遗漏和事件消歧/答题选择混合，不能归为全部相关事实消失。

原始来源检查标签：`confirmed_raw_gap_and_reader_disambiguation`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D28:12 | D28:12 |
| recall 原文中出现的参考 ID | D28:12 | D28:12 |
| 最终上下文中出现的参考 ID | D28:12 | 无 |
| 最终记忆 tokens | 7884 | 8006 |

### conv-47-q56

原始题号：`conv-47_q56`。类别：1。判定：通过 → 未通过。

问题：Which of James's family members have visited him in the last year?

原始评分参考：

> ["mother, sister"]

**基线答案**

> James was visited by his sister on July 21, 2022, and his mother on October 19, 2022. His mother brought her army friend along.

**窗口方案答案**

> James’s mother visited him on October 19, 2022, accompanied by her army friend. No other family members are explicitly recorded as having visited him in the last year.

**原始裁判理由**

- 基线：The generated answer identifies James's mother and sister as visitors, matching the gold answer.
- 窗口：The answer mentions James’s mother but omits his sister and explicitly denies any other family visits, contradicting the gold answer.

原版答案 F1：0.266667 → 0.125000。

**来源核查与归因边界**

新上下文仍有与sister看日落及相处的事实，但明确来访的D17:28原句已返回未打包；reader只确认mother visit。是具体访问关系原句遗漏，不能说所有sister记忆都没有。

原始来源检查标签：`confirmed_specific_relation_context_gap`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D17:28、D28:19 | D17:28、D28:19 |
| recall 原文中出现的参考 ID | D17:28、D28:19 | D17:28、D28:19 |
| 最终上下文中出现的参考 ID | D17:28、D28:19 | 无 |
| 最终记忆 tokens | 7918 | 7967 |

### conv-48-q188

原始题号：`conv-48_q188`。类别：4。判定：通过 → 未通过。

问题：What outdoor activity did Jolene suggest doing together with Deborah?

原始评分参考：

> ["Surfing"]

**基线答案**

> Jolene suggested going surfing together with Deborah in October 2023.

**窗口方案答案**

> Jolene suggested watching the sunrise together with Deborah.

**原始裁判理由**

- 基线：The generated answer correctly identifies surfing as the outdoor activity Jolene suggested doing with Deborah.
- 窗口：The generated answer says watching the sunrise, whereas the gold answer specifies surfing.

原版答案 F1：0.181818 → 0.000000。

**来源核查与归因边界**

新旧事实首项都明确两人计划October surfing，新原文同时包含watch sunrise together，且D29:27已打包。新reader改答sunrise而被判错；多条活动竞争/题意歧义，不能归因于surfing事实未召回或8K截断。

原始来源检查标签：`confirmed_reader_selection_with_competing_events`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D29:27 | D29:27 |
| recall 原文中出现的参考 ID | D29:27 | D29:27 |
| 最终上下文中出现的参考 ID | D29:27 | D29:27 |
| 最终记忆 tokens | 7746 | 8002 |

### conv-49-q104

原始题号：`conv-49_q104`。类别：4。判定：通过 → 未通过。

问题：What food did Sam share a photo of on 19 August, 2023?

原始评分参考：

> ["bowl of spinach, avocado, and strawberries"]

**基线答案**

> Sam shared a photo of grilled chicken and vegetable stir-fry with homemade sauce. He also shared a photo of a spinach, avocado, and strawberry salad that day.

**窗口方案答案**

> Sam shared a photo of grilled chicken and vegetable stir-fry with homemade sauce.

**原始裁判理由**

- 基线：The generated answer includes the spinach, avocado, and strawberry salad, matching the gold answer despite adding another dish.
- 窗口：The generated answer names chicken stir-fry rather than the bowl of spinach, avocado, and strawberries in the gold answer.

原版答案 F1：0.296296 → 0.125000。

**来源核查与归因边界**

D8:1 spinach/avocado/strawberries在recall原文，但新窗口完全未包含这些词，旧上下文含salad且旧答案同时列stir-fry和salad而判对。当前是明确窗口回退和日期下多道菜选择问题。

原始来源检查标签：`confirmed_context_regression`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D8:1 | D8:1 |
| recall 原文中出现的参考 ID | D8:1 | D8:1 |
| 最终上下文中出现的参考 ID | D8:1 | 无 |
| 最终记忆 tokens | 7836 | 7954 |

### conv-50-q130

原始题号：`conv-50_q130`。类别：4。判定：通过 → 未通过。

问题：How does Calvin balance his job and personal life?

原始评分参考：

> ["Takes it one day at a time"]

**基线答案**

> Calvin admits that balancing his music career—especially touring with Frank Ocean—with his personal life is difficult and sometimes overwhelming. He manages it by:
> - Taking things one day at a time and relying on friends and his team for support, as he explained on October 23, 2023.
> - Taking breaks and enjoying favorite activities to recharge, including working on cars and going for relaxing drives.
> - Keeping work and relaxation spaces separate: as of November 2, 2023, he uses his studio only for work and unwinds in a separate cozy room with a TV.
>
> His enjoyment of performing and connecting with audiences also helps him stay motivated despite the demands.

**窗口方案答案**

> Calvin admits that balancing his music career, touring with Frank Ocean, and personal life is challenging. He manages it by relying on friends and his team for support, taking breaks to recharge, and making time for relaxing activities such as working on cars, taking long drives, and enjoying nature. He also separates work from downtime: as of November 2, 2023, he kept his music studio for work and used a separate cozy room with a TV to unwind and find inspiration.

**原始裁判理由**

- 基线：The generated answer explicitly says Calvin takes things one day at a time, matching the gold answer.
- 窗口：The generated answer lists coping strategies but does not mention Calvin's approach of taking it one day at a time.

原版答案 F1：0.118812 → 0.075949。

**来源核查与归因边界**

回退：D25:4 one day at a time在recall回包，但新8K正文与事实均无该短语，旧答案明确使用而判对。属于实际窗口选择回退，不能只看新答案列了很多其他策略便称回答完整。

原始来源检查标签：`confirmed_context_regression`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D25:4 | D25:4 |
| recall 原文中出现的参考 ID | D25:4 | D25:4 |
| 最终上下文中出现的参考 ID | D25:4 | 无 |
| 最终记忆 tokens | 7712 | 7966 |

### conv-50-q136

原始题号：`conv-50_q136`。类别：4。判定：通过 → 未通过。

问题：When did Dave sell the car he restored last year?

原始评分参考：

> ["Last year"]

**基线答案**

> Dave sold the car to a collector sometime after restoring it in 2022 and before his October 23, 2023 conversation. The exact sale date is not specified.

**窗口方案答案**

> Dave sold the car to a collector after restoring it in 2022 and before mentioning the sale on October 23, 2023. The exact sale date is not specified.

**原始裁判理由**

- 基线：The answer places the sale after the 2022 restoration and before October 2023, broadly consistent with the gold answer’s reference to last year despite lacking an exact date.
- 窗口：The generated answer gives only a broad sale window rather than identifying the sale as occurring last year.

原版答案 F1：0.000000 → 0.000000。

**来源核查与归因边界**

新旧答案几乎同义，均说2022恢复之后、October23 2023之前售出且日期不详；旧judge宽松接受，新judge拒绝非last year。D25:17只明确restored last year，没有明确售出也在去年。主要是裁判差异与时间修饰范围歧义，不能当检索未召回。

原始来源检查标签：`confirmed_judge_and_temporal_scope_ambiguity`。

| 参考证据位置诊断 | 基线 | 窗口方案 |
| --- | --- | --- |
| 原标注证据 ID | D25:17 | D25:17 |
| recall 原文中出现的参考 ID | D25:17 | D25:17 |
| 最终上下文中出现的参考 ID | D25:17 | D25:17 |
| 最终记忆 tokens | 7552 | 7979 |

## 补充上下文核查来源

11月20日仅只读检查了conv-26的q21、q26、q80、q85、q132、q133、q135两轮已保存的 `results/<question_id>.json` 中的 `amb_result.context`。基线档案为 `.local/runs/locomo1540r_20261119_030518/`，窗口档案为 `.local/runs/locomow8c_20261119_1506/`；本机档案不随Git共享，逐题结论已写入上文，最终导出文件指纹如下。没有新增HTTP、答题、判题或修改原归档。

## 记录来源

| 归档 | 运行标识 | SHA256 |
| --- | --- | --- |
| [locomo1540-baseline-20261119.json](results/locomo1540-baseline-20261119.json) | `locomo1540r_20261119_030518` | `64e44157d56f6a4a78ae7d31be1be0999cef36f7606fb0272717d85547882a19` |
| [locomo1540-window-20261119.json](results/locomo1540-window-20261119.json) | `locomow8c_20261119_1506` | `c621bf38ac2b3d58bb9c0bca280de286e37bbeeb72cb848fcbe5b7ab707d24db` |
| [locomo1540-window-diagnostics-20261119.json](results/locomo1540-window-diagnostics-20261119.json) | `locomow8c_20261119_1506` | `0ccc21fb2fc155dc77c49a377e17e6f3ade8d298193312732f61f2d1fae2a960` |

整理日期为2026年11月20日，实验结果为2026年11月19日。本附录未新增模型调用、重判或服务端改动。
