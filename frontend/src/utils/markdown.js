/**
 * 将 Dify/大模型返回的常用 Markdown 安全转换为 HTML。
 *
 * 安全原则：
 * - 所有模型返回内容先做 HTML 转义；
 * - 不执行模型返回的原始 HTML；
 * - 只支持标题、加粗、斜体、行内代码、链接、列表、任务列表、
 *   引用、分隔线和简单表格。
 */

export function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function renderInline(value) {
  let text = escapeHtml(value)

  text = text.replace(/`([^`]+)`/g, '<code>$1</code>')
  text = text.replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/__([\s\S]+?)__/g, '<strong>$1</strong>')
  text = text.replace(/(^|[^*])\*([^*\n]+?)\*/g, '$1<em>$2</em>')
  text = text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  )

  return text
}

function splitTableRow(line) {
  return String(line || '')
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isTableSeparator(line) {
  const cells = splitTableRow(line)
  return (
    cells.length > 0
    && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
  )
}

function normalizeSource(markdown) {
  return String(markdown ?? '')
    .replace(/\r\n?/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/^```(?:markdown|md|text)?\s*$/gim, '')
    .replace(/^```\s*$/gim, '')
    .replace(/^[ \t]+(?=#{1,6}\s*)/gm, '')
    .replace(/^＃+/gm, (value) => '#'.repeat(value.length))
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function renderSafeMarkdown(markdown) {
  const source = normalizeSource(markdown)

  if (!source) {
    return '<p class="markdown-empty">暂无内容</p>'
  }

  const lines = source.split('\n')
  const html = []
  let listType = ''

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`)
      listType = ''
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index]
    const line = rawLine.trim()

    if (!line) {
      closeList()
      continue
    }

    if (
      line.includes('|')
      && index + 1 < lines.length
      && isTableSeparator(lines[index + 1])
    ) {
      closeList()

      const headers = splitTableRow(line)
      const rows = []
      index += 2

      while (
        index < lines.length
        && lines[index].includes('|')
        && lines[index].trim()
      ) {
        rows.push(splitTableRow(lines[index]))
        index += 1
      }

      index -= 1
      html.push('<div class="markdown-table-wrap"><table><thead><tr>')
      headers.forEach((cell) => {
        html.push(`<th>${renderInline(cell)}</th>`)
      })
      html.push('</tr></thead><tbody>')

      rows.forEach((row) => {
        html.push('<tr>')
        headers.forEach((_, cellIndex) => {
          html.push(`<td>${renderInline(row[cellIndex] || '')}</td>`)
        })
        html.push('</tr>')
      })

      html.push('</tbody></table></div>')
      continue
    }

    /* 同时兼容 "# 标题" 和 "##标题" */
    const heading = line.match(/^(#{1,6})\s*(.+)$/)
    if (heading) {
      closeList()
      const level = Math.min(heading[1].length, 4)
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`)
      continue
    }

    if (/^[-*_]{3,}$/.test(line)) {
      closeList()
      html.push('<hr>')
      continue
    }

    const quote = line.match(/^>\s*(.+)$/)
    if (quote) {
      closeList()
      html.push(`<blockquote>${renderInline(quote[1])}</blockquote>`)
      continue
    }

    const task = line.match(/^[-*•]\s+\[([ xX])\]\s+(.+)$/)
    if (task) {
      if (listType !== 'ul') {
        closeList()
        listType = 'ul'
        html.push('<ul class="task-list">')
      }

      const checked = task[1].toLowerCase() === 'x'
      html.push(
        `<li><span class="task-check ${checked ? 'checked' : ''}">`
        + `${checked ? '✓' : ''}</span>${renderInline(task[2])}</li>`
      )
      continue
    }

    const unordered = line.match(/^[-*•]\s+(.+)$/)
    if (unordered) {
      if (listType !== 'ul') {
        closeList()
        listType = 'ul'
        html.push('<ul>')
      }

      html.push(`<li>${renderInline(unordered[1])}</li>`)
      continue
    }

    const ordered = line.match(/^\d+[.、)]\s*(.+)$/)
    if (ordered) {
      if (listType !== 'ol') {
        closeList()
        listType = 'ol'
        html.push('<ol>')
      }

      html.push(`<li>${renderInline(ordered[1])}</li>`)
      continue
    }

    closeList()
    html.push(`<p>${renderInline(line)}</p>`)
  }

  closeList()
  return html.join('')
}
