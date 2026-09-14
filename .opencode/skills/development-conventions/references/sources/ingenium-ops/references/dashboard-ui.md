# Dashboard UI Patterns

## Card Component
- Rounded corners (`rounded-lg`)
- Border (`border border-gray-200`)
- White background (`bg-white`)
- Hover shadow (`hover:shadow-md transition-shadow`)
- Cursor pointer (`cursor-pointer`)
- onClick → sets selected item state → renders overlay

## Overlay Component (Overlay.tsx)
- Full-screen fixed overlay with backdrop (`bg-black/30`)
- Centered modal (`max-w-2xl w-full`)
- Close button (X) and backdrop click to dismiss
- Children render inside modal with overflow scroll

## MarkdownViewer Component
- Toggle between "Preview" and "Source" tabs
- Preview: renders markdown to HTML with `react-markdown` + `remark-gfm`
- Source: renders in `<pre>` block with gray background

## Pages
All pages follow this structure:
```
Page Heading (h1)
Search / Create bar (if applicable)
Card grid (responsive: 1 col sm:2 lg:3)
Overlay (conditional on selectedItem)
```
