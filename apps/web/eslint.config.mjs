import js from '@eslint/js'
import next from 'eslint-config-next'
import tseslint from 'typescript-eslint'

/**
 * Flat config（ESLint 9 原生格式）。
 *
 * 为什么不用 `next lint`：该命令在 Next 16 已废弃，package.json 里的
 * `next lint` 实际会把 "lint" 当成目录名报错——即项目的 lint 从未真正跑过，
 * 这是 §16.8 那批 useCallback 滥用长期没被发现的原因。
 *
 * 为什么必须用 typescript-eslint：ESLint 内置的 no-unused-vars / no-undef
 * 不认 TS 语法，会把 `import * as React`、类型注解、双重声明全判成「未使用」。
 * 实测误报 84 处，直接把 lint 信号淹掉。换成 typescript-eslint 后归零。
 */
export default [
  // ignore 必须独立成块且放最前，否则不生效（.next 构建产物会被扫进去）
  {
    ignores: ['.next/**', 'node_modules/**', 'out/**', 'next-env.d.ts'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...next,
  {
    rules: {
      // 关掉内置的两条——已由 typescript-eslint 的同名规则接管
      'no-unused-vars': 'off',
      'no-undef': 'off',

      // §16.8 Hook 使用规则
      // 依赖数组必须诚实——闭包里读了什么就写什么，禁止靠 disable 蒙混
      'react-hooks/exhaustive-deps': 'error',
      'react-hooks/rules-of-hooks': 'error',
    },
  },
]