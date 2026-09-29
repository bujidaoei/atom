PLAN_SYSTEM = """只返回一个 JSON 对象，不要 Markdown。
字段：
- name：不超过 12 个字
- lead：两句，第一版做什么、明确不做什么
- research：两句。只根据用户的描述判断谁在用、最大的风险。不要假装做过外部调研，不要编数字
- architecture：一句，必须写出 localStorage 的键名
- requirements：正好 4 条

每条需求含 key、title、detail、priority、checks。
key 用 R1、R2、R3、R4。priority 都是 must。checks 最多 2 个，只能是这三种：
{"op":"exists","selector":"#id"}
{"op":"text","contains":"首屏正文里就有的文字"}
{"op":"flow","steps":[{"do":"fill","selector":"#id","value":"样本"},{"do":"click","selector":"#id"},{"do":"see","contains":"样本"}]}
id 以字母开头。text 的文字必须能写进初始 HTML，不能是点完才出现的。四条里只给一条 flow，see 的文字就用 fill 的 value。
"""

BUILD_SYSTEM = """按这个顺序输出三段，不要用 Markdown 围栏。

NOTES
两句中文。

TRACE
每条需求一行：R1 | 用哪个元素完成

HTML
从 <!DOCTYPE html> 到 </html>。

规则：CSS 和 JS 都写在这个文件里，不要外链，不要框架。界面用中文。
背景 #f6f3ec，文字 #1c1915，强调色 #8f4318。标题用 Palatino, serif。
契约里每个 #id 在首屏就存在。text 检查的句子写在正文里。
用 click 和 input 立刻改 DOM，不要让表单刷新整页。
游戏或需要操作的页面，把开始、方向、确认做成页面上的按钮。不能只依赖键盘，预览框里点按钮就能玩。
要记住的内容写入架构说明里的 localStorage 键。
整个 HTML 控制在 140 行以内。按钮和标题用用户能看懂的话，不要写“测试”“示例”“TODO”。
"""

CLASSIFY_SYSTEM = """判断修改会不会推翻已锁定的 must 需求。只返回 JSON。
只改颜色、文案、间距：{"kind":"compatible","reason":"一句话"}
删掉、反转或换成另一件事：{"kind":"amend","reason":"一句话","requirements":[完整的 4 条新契约]}
新契约字段和检查格式与原来相同。不要编数字。
"""

REPAIR_HINT = "上次的页面没通过检查。请重新输出 NOTES、TRACE、HTML，补上缺失的 id 和点击后立刻出现的文字。HTML 仍控制在 100 行以内。"
