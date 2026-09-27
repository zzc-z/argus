// *.module.css — CSS Modules 类型声明（Next 15 内置支持）
declare module '*.module.css' {
  const classes: { readonly [key: string]: string }
  export default classes
}
