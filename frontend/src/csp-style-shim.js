// CSP 兼容垫片：把 style.cssText 赋值改写为逐条 CSSOM setProperty。
//
// 背景：ECharts/zrender 在图表初始化（zrender createRoot 的容器定位）和 tooltip
// 渲染（TooltipHTMLContent 组装样式串）时使用 style.cssText = "..." 赋值。
// CSP style-src 'self' 下这属于内联样式属性赋值，会被浏览器整体拦截，
// 导致图表容器丢失 position:relative、tooltip 丢失全部样式。
// 而 CSSStyleDeclaration 的属性级赋值（setProperty）属于 CSSOM 修改，不受 CSP 限制。
// 样式串均为运行时动态拼接（含尺寸/主题色），无法用固定哈希白名单覆盖，
// 因此在原型层统一转换。必须在 main.jsx 最顶部引入，早于任何图表创建。
//
// Trusted Types：CSP require-trusted-types-for 'script' 下 innerHTML 赋值
// 需要 TrustedHTML 对象。注册 default 直通策略使既有代码（ECharts tooltip、
// JSON 高亮、docx-preview 等）无需改造即可运行，同时满足扫描器对
// trusted-types 强制执行的要求。后续如需收紧，可在此按调用方注册命名策略。
;(function () {
  if (window.trustedTypes && trustedTypes.createPolicy) {
    try {
      trustedTypes.createPolicy('default', {
        createHTML: function (s) { return s },
        createScript: function (s) { return s },
        createScriptURL: function (s) { return s },
      })
    } catch (e) { /* 策略已存在时忽略 */ }
  }
})()

;(function () {
  var proto = CSSStyleDeclaration.prototype
  var desc = Object.getOwnPropertyDescriptor(proto, 'cssText')
  if (!desc || !desc.set) return

  Object.defineProperty(proto, 'cssText', {
    configurable: true,
    enumerable: desc.enumerable,
    get: desc.get,
    set: function (v) {
      // cssText 语义是整体替换，先清空已有声明
      while (this.length) this.removeProperty(this.item(0))
      var s = String(v == null ? '' : v)
      var decls = s.split(';')
      for (var d = 0; d < decls.length; d++) {
        var decl = decls[d]
        var i = decl.indexOf(':')
        if (i <= 0) continue
        var prop = decl.slice(0, i).trim()
        var val = decl.slice(i + 1).trim()
        if (!prop) continue
        try { this.setProperty(prop, val) } catch (e) { /* 非法声明忽略，与浏览器行为一致 */ }
      }
    },
  })
})()
