# Atoms 设计系统（从 atoms.dev 线上站点提取）

以下 token 是 2026-09-29 直接从 `https://atoms.dev/zh` 的 `:root` 计算样式里读出来的，
不是照截图临摹。前端必须以这份为准，不要自己发明色值。

提取方式：`getComputedStyle` + 遍历 `document.styleSheets` 收集 `--*` 自定义属性。

---

## 1. 基础色阶（原始值）

```css
--beige-50:  #ffffff;
--beige-100: #f6f6f6;
--beige-150: #f1f1f1;
--beige-200: #ebebea;

--grey-700: #353536;
--grey-750: #2c2c2d;
--grey-800: #232324;
--grey-900: #171717;

--blue-100: #dde7ff;
--blue-300: #9ab4ff;
--blue-400: #7d9aff;
--blue-500: #4267ff;   /* 品牌主色 */
--blue-600: #425ce1;
--blue-700: #293a90;
--blue-800: #212675;

--red-400: #fb7274;
--red-500: #c9444a;
--red-600: #b72027;

--green-400: #57c675;
--green-600: #25813c;
```

## 2. Alpha 阶

```css
--alpha-black-2:  rgba(12,12,12,.02);
--alpha-black-4:  rgba(12,12,12,.04);
--alpha-black-6:  rgba(12,12,12,.06);
--alpha-black-8:  rgba(12,12,12,.08);
--alpha-black-12: rgba(12,12,12,.12);
--alpha-black-30: rgba(12,12,12,.30);
--alpha-black-40: rgba(12,12,12,.40);
--alpha-black-55: rgba(12,12,12,.55);
--alpha-black-80: rgba(12,12,12,.80);
--alpha-black-95: rgba(12,12,12,.95);
--alpha-black-100:#0c0c0c;

--alpha-white-4:  hsla(0,0%,100%,.04);
--alpha-white-8:  hsla(0,0%,100%,.08);
--alpha-white-12: hsla(0,0%,100%,.12);
--alpha-white-16: hsla(0,0%,100%,.16);
--alpha-white-20: hsla(0,0%,100%,.20);
--alpha-white-40: hsla(0,0%,100%,.40);
--alpha-white-60: hsla(0,0%,100%,.60);
--alpha-white-80: hsla(0,0%,100%,.80);
--alpha-white-95: hsla(0,0%,100%,.95);

--alpha-blue-8:  rgba(61,99,255,.08);
--alpha-blue-12: rgba(61,99,255,.12);
--alpha-blue-16: rgba(61,99,255,.16);
--alpha-blue-25: rgba(61,99,255,.25);
--alpha-blue-30: rgba(61,99,255,.30);
--alpha-blue-40: rgba(61,99,255,.40);
```

## 3. 语义层

关键：Atoms 的亮/暗主题**共用同一套语义名**，只换底下指向的原始值。
所以组件里**只准用语义 token**，不准直接写 `#4267ff`。

亮色（默认）：

```css
--color-bg-base-default:        var(--beige-200);  /* 页面底色 #ebebea */
--color-bg-base-default-low:    var(--beige-50);
--color-bg-base-secondary:      var(--beige-100);
--color-bg-base-secondary-alt:  var(--beige-150);
--color-bg-base-tertiary:       var(--beige-50);   /* 卡片白 */

--color-bg-brand-default:       var(--blue-500);
--color-bg-brand-secondary:     var(--blue-400);
--color-bg-brand-tertiary:      var(--blue-300);
--color-bg-alpha-brand-secondary: var(--alpha-blue-12);
--color-bg-alpha-brand-tertiary:  var(--alpha-blue-8);

--color-bg-neutral-white-4:   var(--alpha-black-2);
--color-bg-neutral-white-8:   var(--alpha-black-4);
--color-bg-neutral-white-12:  var(--alpha-black-6);
--color-bg-neutral-white-16:  var(--alpha-black-8);
--color-bg-neutral-white-20:  var(--alpha-black-12);

--color-border-neutral-white-8:  var(--alpha-black-4);
--color-border-neutral-white-12: var(--alpha-black-6);
--color-border-neutral-white-16: var(--alpha-black-12);
--color-border-brand-default:    var(--blue-600);
--color-border-danger-default:   var(--red-600);

--color-text-neutral-white-95: var(--alpha-black-95);  /* 主文案 */
--color-text-neutral-white-80: var(--alpha-black-80);  /* 次文案 */
--color-text-neutral-white-60: var(--alpha-black-55);  /* 弱文案 */
--color-text-neutral-white-40: var(--alpha-black-30);  /* 占位/禁用 */
--color-text-neutral-inverse-95: var(--alpha-white-95);
--color-text-brand-default:    var(--blue-600);

--color-bg-utilities-header: hsla(0,0%,90%,.7);   /* 顶栏，配 backdrop-blur */
--color-bg-utilities-footer: #232324;
--color-bg-utilities-tab:    hsla(0,0%,100%,.95);
```

暗色（`.dark`）：整体反转，`--color-bg-base-default` → `--grey-800`，
`--color-text-neutral-white-95` → `--alpha-white-95`，`neutral-white-N` 系列由
`alpha-black-*` 换成 `alpha-white-*`。品牌蓝在暗色下文字用 `--blue-400`。

## 4. 圆角与间距

```css
--origin-2:2px;  --origin-4:4px;   --origin-6:6px;   --origin-8:8px;
--origin-12:12px; --origin-16:16px; --origin-24:24px; --origin-32:32px;
--origin-48:48px; --origin-full:999px;

--radius-m:    8px;
--radius-l:   12px;
--radius-xl:  16px;
--radius-full:999px;

--spacing-xxxs:2  --spacing-xxs:4  --spacing-xs:6  --spacing-s:8
--spacing-m:12    --spacing-l:16   --spacing-xl:24 --spacing-xxl:32
--spacing-xxxl:48
```

**Composer（首页/Dashboard 输入框）是唯一的例外**：`border-radius: 24px`，
`padding: 16px`，`border: 0.667px solid`，`box-shadow: 0 1px 4px rgba(12,12,12,.08)`。

## 5. 字体

```
font-family: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
base font-size: 14px      ← 注意不是 16px
h1: 32px / line-height 40px / weight 500
```

中文回退需补：`"PingFang SC", "Microsoft YaHei", "Noto Sans SC"`。
代码用 `"IBM Plex Mono", ui-monospace`。

**不要用 Inter / Roboto。** IBM Plex Sans 有 Google Fonts CDN。

## 6. 动效

```css
--sidebar-motion-duration-expand:   .82s;
--sidebar-motion-ease-expand:   cubic-bezier(.01, .99, .49, 1.01);
--sidebar-motion-duration-collapse: .46s;
--sidebar-motion-ease-collapse: cubic-bezier(.08, .57, .02, 1);
```

一般交互（hover / 按钮 / 卡片）用 `150ms cubic-bezier(.4,0,.2,1)`。
侧边栏展开收起必须用上面那两条，这是 Atoms 很有辨识度的一个细节。
`prefers-reduced-motion` 下全部降到 0。

## 7. 观察到的版式特征

- 页面底色是浅灰 `#ebebea`，卡片是纯白，靠**极细的 alpha 边框**而不是阴影分层。
  阴影只有一档：`0 1px 4px rgba(12,12,12,.08)`。
- 主按钮是**蓝色胶囊**（`radius-full`，`--blue-500` 底，白字）。
- 左侧栏可折叠，宽约 164px，项目列表在下方，底部固定"升级/免费额度"两个入口。
- Dashboard 中央是 8 个 agent 的 3D 头像一字排开 + 一句大标题 + Composer。
- 首页 hero 标题 `32px/500`，不是常见的超大字重 bold。
- 顶部有一条可关闭的 Notice 胶囊条。

## 8. Agent 头像

Atoms 用的是 8 个 3D 渲染的卡通角色头像。我们没有这些素材，**不要用 SVG 手绘人脸**，
也不要用 emoji 替代。做法：每个角色一个圆形色块 + 首字母，颜色从下表取，
保证 5 个角色在时间线上可区分。

| 角色 | 职责 | 色 |
|---|---|---|
| Mike | Team Leader | `--blue-500` |
| Iris | Deep Researcher | `#8b5cf6` |
| Emma | Product Manager | `--green-400` |
| Bob | Architect | `#f59e0b` |
| Alex | Engineer | `--grey-700` |

（Atoms 另有 Sarah SEO / Adrian Ads / David Data Analyst，本 Demo 不实现，
但在 UI 上以"未启用"状态展示，说明产品完整形态。）
