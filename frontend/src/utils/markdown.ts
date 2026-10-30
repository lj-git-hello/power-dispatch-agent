/**
 * 工业级 Markdown 渲染工具（面向 Agent 流式回答）
 *
 * 技术栈：markdown-it（解析）+ highlight.js（代码高亮，按需注册语言）
 *        + KaTeX（数学公式）+ DOMPurify（XSS 防护）。
 * 输出为已清洗的安全 HTML 片段，可直接用于 v-html；流式场景每帧全量重算。
 */
import MarkdownIt from 'markdown-it';
import type { PluginSimple, RendererRule } from 'markdown-it';
import * as markdownItKatexModule from '@vscode/markdown-it-katex';
import hljs from 'highlight.js/lib/core';
import DOMPurify from 'dompurify';

// 样式副作用引入（全局 CSS，对 v-html 挂载内容生效）
import 'katex/dist/katex.min.css';
import 'highlight.js/styles/github.css';

// ---- highlight.js 按需注册常用语言（控制产物体积） ----
import python from 'highlight.js/lib/languages/python';
import bash from 'highlight.js/lib/languages/bash';
import sql from 'highlight.js/lib/languages/sql';
import json from 'highlight.js/lib/languages/json';
import javascript from 'highlight.js/lib/languages/javascript';
import typescript from 'highlight.js/lib/languages/typescript';
import yaml from 'highlight.js/lib/languages/yaml';
import xml from 'highlight.js/lib/languages/xml';

hljs.registerLanguage('python', python);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('sh', bash);
hljs.registerLanguage('shell', bash);
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('json', json);
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('js', javascript);
hljs.registerLanguage('typescript', typescript);
hljs.registerLanguage('ts', typescript);
hljs.registerLanguage('yaml', yaml);
hljs.registerLanguage('yml', yaml);
hljs.registerLanguage('xml', xml);
hljs.registerLanguage('html', xml);

/** HTML 特殊字符转义（高亮异常时的安全兜底） */
function escapeHtml(raw: string): string {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** 将高亮结果包裹为完整代码块（markdown-it 拿到非空串后不再二次包裹） */
function wrapHighlighted(inner: string): string {
  return `<pre class="hljs"><code>${inner}</code></pre>`;
}

/** markdown-it 单例：禁原生 HTML、自动链接、换行转 <br>，自定义高亮 */
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight: (code: string, lang: string): string => {
    try {
      if (lang && hljs.getLanguage(lang)) {
        return wrapHighlighted(hljs.highlight(code, { language: lang }).value);
      }
      // 未声明或未注册语言：自动探测，避免无配色的裸代码
      return wrapHighlighted(hljs.highlightAuto(code).value);
    } catch {
      return wrapHighlighted(escapeHtml(code));
    }
  },
});

/**
 * 该插件为 CJS（module.exports = { default: fn }），不同打包器对 default 的
 * 互操作嵌套层级不一（Vite dev 可能为两层 .default），逐层解开取出函数本体。
 */
function resolvePlugin(holder: unknown): PluginSimple {
  let cur: unknown = holder;
  for (let i = 0; i < 3 && cur && typeof cur === 'object'; i += 1) {
    if ('default' in cur) {
      const next = (cur as { default: unknown }).default;
      if (typeof next === 'function') return next as PluginSimple;
      cur = next;
    } else {
      break;
    }
  }
  if (typeof cur === 'function') return cur as PluginSimple;
  throw new Error('无法解析 markdown-it-katex 插件函数');
}

md.use(resolvePlugin(markdownItKatexModule));

// 链接默认在新标签页安全打开
const defaultLinkRender: RendererRule =
  md.renderer.rules.link_open ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank');
  tokens[idx].attrSet('rel', 'noopener noreferrer');
  return defaultLinkRender(tokens, idx, options, env, self);
};

/** KaTeX 输出的 MathML 标签 / 属性白名单（DOMPurify 默认 HTML 白名单不含 MathML） */
const KATEX_MATHML_TAGS: readonly string[] = [
  'math',
  'semantics',
  'annotation',
  'mrow',
  'mi',
  'mo',
  'mn',
  'ms',
  'mtext',
  'mspace',
  'mstyle',
  'mfrac',
  'msqrt',
  'mroot',
  'merror',
  'mpadded',
  'mphantom',
  'menclose',
  'mfenced',
  'mtable',
  'mlabeledtr',
  'mtr',
  'mtd',
  'msub',
  'msup',
  'msubsup',
  'munder',
  'mover',
  'munderover',
];

const KATEX_MATHML_ATTRS: readonly string[] = [
  'encoding',
  'display',
  'mathvariant',
  'mathsize',
  'mathcolor',
  'columnalign',
  'columnlines',
  'columnspan',
  'columnwidth',
  'frame',
  'framespacing',
  'rowalign',
  'rowlines',
  'rowspan',
  'width',
  'height',
  'depth',
  'lspace',
  'voffset',
  'accent',
  'accentunder',
  'align',
  'bevelled',
  'close',
  'denomalign',
  'displaystyle',
  'fence',
  'form',
  'largeop',
  'linethickness',
  'lquote',
  'maxsize',
  'minsize',
  'movablelimits',
  'notation',
  'numalign',
  'open',
  'overflow',
  'position',
  'rquote',
  'rspace',
  'separator',
  'separators',
  'stretchy',
  'subscriptshift',
  'superscriptshift',
  'symmetric',
  'valign',
];

/**
 * 将 Markdown 源文本渲染为经 DOMPurify 清洗的安全 HTML 片段。
 * 流式场景下输入未闭合的代码块/公式可安全降级。
 */
export function renderMarkdown(raw: string): string {
  if (!raw) return '';
  return DOMPurify.sanitize(md.render(raw), {
    ADD_TAGS: [...KATEX_MATHML_TAGS],
    ADD_ATTR: [...KATEX_MATHML_ATTRS],
  });
}
