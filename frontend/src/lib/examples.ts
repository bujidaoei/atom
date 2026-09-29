export type ExamplePrompt = {
  kind: string;
  label: string;
  title: string;
  prompt: string;
};

/** Gallery entries for 能构建什么 — clicking one prefills the composer. */
export const EXAMPLE_PROMPTS: ExamplePrompt[] = [
  {
    kind: "tool",
    label: "工具",
    title: "记账小工具",
    prompt:
      "做一个记账小工具：可以新增一笔收支、按分类筛选、顶部显示本月结余，数据存在 localStorage。",
  },
  {
    kind: "landing",
    label: "落地页",
    title: "独立咖啡馆落地页",
    prompt:
      "做一个独立咖啡馆的落地页：招牌豆子介绍、营业时间、地图区块和一个留邮箱的订阅表单。",
  },
  {
    kind: "dashboard",
    label: "看板",
    title: "团队周报看板",
    prompt:
      "做一个团队周报看板：左侧成员列表，右侧本周进展卡片，支持按状态过滤和一个完成率进度条。",
  },
  {
    kind: "game",
    label: "小游戏",
    title: "键盘打字练习",
    prompt: "做一个键盘打字练习页：随机句子、实时计算 WPM 和准确率、结束后给出成绩卡。",
  },
  {
    kind: "store",
    label: "商店",
    title: "手作陶器小店",
    prompt:
      "做一个手作陶器小店：商品网格、点开有详情抽屉、可加入购物车并在右上角显示件数与合计。",
  },
  {
    kind: "portfolio",
    label: "作品集",
    title: "摄影作品集",
    prompt: "做一个摄影作品集：瀑布流图集、按系列切换标签、点击图片全屏查看并可左右切换。",
  },
];
