/**
 * Commit message 格式校验（Conventional Commits）。
 *
 * 由 apps/web/.husky/commit-msg 自动执行，配错会拦住**所有**提交——
 * 装依赖时留意这一点。
 */
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // scope 可选：允许 "feat: xxx" 这种不带 scope 的写法
    'scope-enum': [0],
    // 标题长度上限 100，与团队现有 commit 风格一致
    'header-max-length': [2, 'always', 100],
    // 允许 body 里有连续空行
    'body-max-line-length': [0],
    // 本项目 commit 标题是中文。subject-case（首字母大写 / 不得以句号结尾）
    // 是给英文设计的规则，套到中文上会把中文逗号误判成句末而报错。
    'subject-case': [0],
  },
}
