// CSP style-src 'self' 兼容垫片：消除页面运行时的全部内联样式依赖。
//
// 背景：CSP style-src 不含 'unsafe-inline' 时，浏览器拦截所有内联样式，
// 而 ECharts 等库的运行时样式无法用固定哈希白名单覆盖（值随主题色/尺寸动态变化）。
// CSSOM 属性级赋值（setProperty）不受 CSP 限制，因此在此原型层统一转换。
// 必须在 main.jsx 最顶部引入，早于任何图表创建。
//
// 覆盖三条内联样式注入路径：
//  1. style.cssText = "..." 赋值（zrender 图表容器定位、tooltip 容器样式）
//     → 拦截 setter，拆分声明逐条 setProperty
//  2. setAttribute('style', ...) → 同上走 CSSOM
//  3. innerHTML / insertAdjacentHTML 注入的 HTML 字符串里自带的 style="..." 属性
//     （ECharts tooltip 默认 markup：marker 颜色、margin、line-height、float 等）
//     → CSP 拦截时元素仍保留 style 属性（仅样式未生效），赋值完成后遍历 [style]
//       元素，读出属性值经 CSSOM 重放并移除属性
;
(function () {
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

// 把声明串（"a:b;c:d"）经 CSSOM 写入 style 对象；cssText 语义是整体替换
function applyDeclarations(styleObj, cssText) {
  while (styleObj.length) styleObj.removeProperty(styleObj.item(0))
  var decls = String(cssText == null ? '' : cssText).split(';')
  for (var d = 0; d < decls.length; d++) {
    var i = decls[d].indexOf(':')
    if (i <= 0) continue
    var prop = decls[d].slice(0, i).trim()
    var val = decls[d].slice(i + 1).trim()
    if (!prop) continue
    var m = val.match(/^([\s\S]*)!\s*important\s*$/i)
    try {
      if (m) styleObj.setProperty(prop, m[1].trim(), 'important')
      else styleObj.setProperty(prop, val)
    } catch (e) { /* 非法声明忽略，与浏览器行为一致 */ }
  }
}

// 路径 1：cssText setter
;(function () {
  var proto = CSSStyleDeclaration.prototype
  var desc = Object.getOwnPropertyDescriptor(proto, 'cssText')
  if (!desc || !desc.set) return
  Object.defineProperty(proto, 'cssText', {
    configurable: true,
    enumerable: desc.enumerable,
    get: desc.get,
    set: function (v) { applyDeclarations(this, v) },
  })
})()

// 路径 2：setAttribute('style', ...)
;(function () {
  var orig = Element.prototype.setAttribute
  if (!orig) return
  Element.prototype.setAttribute = function (name, value) {
    if (String(name).toLowerCase() === 'style') {
      applyDeclarations(this.style, value)
      return
    }
    return orig.call(this, name, value)
  }
})()

// 路径 3：innerHTML / insertAdjacentHTML 注入的 style 属性重放
;(function () {
  function rescueStyles(root) {
    if (!root || root.nodeType !== 1) return
    var list = []
    if (root.hasAttribute('style')) list.push(root)
    try {
      var nodes = root.querySelectorAll('[style]')
      for (var i = 0; i < nodes.length; i++) list.push(nodes[i])
    } catch (e) { return }
    for (var j = 0; j < list.length; j++) {
      var el = list[j]
      var css = el.getAttribute('style')
      el.removeAttribute('style')
      if (css) { try { applyDeclarations(el.style, css) } catch (e) { /* 忽略 */ } }
    }
  }

  var desc = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML')
  if (desc && desc.set) {
    Object.defineProperty(Element.prototype, 'innerHTML', {
      configurable: true,
      enumerable: desc.enumerable,
      get: desc.get,
      set: function (v) {
        desc.set.call(this, v)
        rescueStyles(this)
      },
    })
  }

  var origIAH = Element.prototype.insertAdjacentHTML
  if (origIAH) {
    Element.prototype.insertAdjacentHTML = function (position, text) {
      origIAH.call(this, position, text)
      rescueStyles(this.parentElement || this)
    }
  }
})()
