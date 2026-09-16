// toolbar.js — single source of truth for every control in the Studio.
//
// Why this file exists: buttons used to live in two places — studio.html for
// the sidebar, and HTML strings inside studio.js for the selection bar. The
// same control could drift apart between them, visibility was hand-written
// `style.display` code, and nobody could see the whole tool set at a glance.
// Here every control is one entry in a list, and both the mode panels and the
// context bar are rendered from that list.
//
// Element ids are part of the contract with studio.js: it binds handlers by id
// (text-input, tpl-list, brush-slider …). Renaming one here breaks the wiring,
// so ids are written out explicitly rather than generated.

/* ---------------------------------------------------------------------------
   Small render helpers. Every spec object has a `t` (type) key.
   --------------------------------------------------------------------------- */

const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const attr = (name, value) =>
  (value === undefined || value === null || value === false) ? '' : ` ${name}="${esc(value)}"`;

function renderItem(it) {
  if (!it) return '';
  switch (it.t) {

    case 'btn':
      return `<button type="button" class="tbtn${it.cls ? ' ' + it.cls : ''}${it.wide ? ' wide' : ''}"`
        + attr('id', it.id) + attr('data-act', it.act) + attr('title', it.title)
        + `>${it.icon ? esc(it.icon) + (it.label ? ' ' : '') : ''}${esc(it.label || '')}</button>`;

    case 'shape':
      return `<button type="button" class="tbtn tbtn-ico"${attr('data-shape', it.shape)}`
        + attr('title', it.title) + `>${esc(it.icon)}</button>`;

    case 'badge':
      return `<button type="button" class="tbtn"${attr('data-badge', it.badge)}`
        + attr('title', it.title) + `>${esc(it.icon)} ${esc(it.label)}</button>`;

    // Retouch tool. `data-tool` carries the legacy tool name so the existing
    // handler in studio.js keeps working unchanged; ui.js rewrites it when the
    // scope (brush / area / whole colour) changes.
    case 'tool':
      return `<button type="button" class="tbtn"${attr('data-tool', it.tool)}`
        + attr('data-toolkey', it.key) + attr('title', it.title)
        + `>${esc(it.icon)} ${esc(it.label)}</button>`;

    case 'mark':
      return `<button type="button" class="tbtn${it.cls ? ' ' + it.cls : ''}"`
        + attr('data-mark', it.mark) + attr('title', it.title)
        + `>${esc(it.icon)} ${esc(it.label)}</button>`;

    case 'out':
      return `<button type="button" class="tbtn${it.on ? ' primary' : ''}"`
        + attr('data-out', it.out) + `>${esc(it.label)}</button>`;

    case 'text':
      return `<input type="text" class="field${it.wide ? ' wide' : ''}"` + attr('id', it.id)
        + attr('placeholder', it.ph) + attr('title', it.title)
        + (it.w ? ` style="width:${it.w}px"` : '') + '>';

    case 'area':
      return `<textarea class="field wide"` + attr('id', it.id) + attr('placeholder', it.ph)
        + ` rows="${it.rows || 2}"></textarea>`;

    case 'num':
      return `<input type="number" class="field field-num"` + attr('id', it.id)
        + attr('value', it.value) + attr('min', it.min) + attr('max', it.max)
        + attr('step', it.step) + attr('title', it.title)
        + (it.w ? ` style="width:${it.w}px"` : '') + '>';

    case 'color':
      return `<input type="color" class="field-color"` + attr('id', it.id)
        + attr('value', it.value) + attr('title', it.title) + '>';

    case 'select':
      return `<select class="field"` + attr('id', it.id) + attr('title', it.title)
        + (it.w ? ` style="width:${it.w}px"` : '') + '>'
        + it.opts.map(o => `<option value="${esc(o.v)}"${o.sel ? ' selected' : ''}>${esc(o.l)}</option>`).join('')
        + '</select>';

    case 'range':
      return `<input type="range" class="tl-slider"` + attr('id', it.id)
        + attr('min', it.min) + attr('max', it.max) + attr('step', it.step)
        + attr('value', it.value) + attr('title', it.title) + '>';

    case 'check':
      return `<label class="check">${renderItem({ t: 'raw', html: `<input type="checkbox"${attr('id', it.id)}>` })}`
        + `<span>${esc(it.label)}</span></label>`;

    case 'file':
      return `<input type="file"` + attr('id', it.id) + attr('accept', it.accept)
        + (it.multiple ? ' multiple' : '') + ' hidden>';

    case 'label':  return `<span class="ctl-label">${esc(it.text)}</span>`;
    case 'hint':   return `<p class="hint">${it.html || esc(it.text)}</p>`;
    case 'link':   return `<a class="manage-link"${attr('href', it.href)}>${esc(it.label)}</a>`;
    case 'sep':    return '<span class="bar-sep"></span>';
    case 'gap':    return `<span class="bar-gap"></span>`;

    // Mount point: studio.js or a module fills this element later.
    case 'mount':
      return `<div${attr('id', it.id)} class="${it.cls || ''}">`
        + (it.placeholder ? `<span class="placeholder">${esc(it.placeholder)}</span>` : '') + '</div>';

    // `hide` starts the row as display:none. setTool() in studio.js switches
    // these rows with style.display, so they must start hidden the same way —
    // otherwise brush size, colour and the mark buttons are all on screen at
    // once before any tool has been picked.
    case 'row':    return `<div class="ctl-row${it.cls ? ' ' + it.cls : ''}"${attr('id', it.id)}`
                          + (it.hide ? ' style="display:none"' : '') + '>'
                          + it.items.map(renderItem).join('') + '</div>';
    case 'grid':   return `<div class="ctl-grid">` + it.items.map(renderItem).join('') + '</div>';
    case 'raw':    return it.html;
    default:       return '';
  }
}

// Class and id are deliberately the old ones: studio.js binds the
// collapse handler to `.sidebar-section h3` and keeps #retouch-section
// permanently open. Renaming them here would silently drop both.
const renderSection = s =>
  `<section class="sidebar-section" id="${s.id}-section">`
  + (s.title ? `<h3>${esc(s.title)}</h3>` : '')
  + `<div class="section-body">${s.items.map(renderItem).join('')}</div></section>`;

/* ---------------------------------------------------------------------------
   Modes — the left rail. Exactly one panel is visible at a time.
   --------------------------------------------------------------------------- */

export const MODES = [
  { id: 'build',  icon: '🗂', label: 'Build',  title: 'Template, canvas and brand colours' },
  { id: 'insert', icon: '➕', label: 'Insert', title: 'Text, shapes and badges' },
  { id: 'image',  icon: '✂',  label: 'Image',  title: 'Cut out and retouch the selected image' },
  { id: 'layers', icon: '☰',  label: 'Layers', title: 'Order and grouping' },
];

/* ---------------------------------------------------------------------------
   Panels. Rendered once at start-up; switching modes only shows/hides them,
   so every handler studio.js binds by id stays alive.
   --------------------------------------------------------------------------- */

export const PANELS = {

  build: [
    { id: 'template', title: 'Template', items: [
      { t: 'mount', id: 'tpl-list', cls: 'tpl-grid', placeholder: 'Loading…' },
      { t: 'row', items: [
        { t: 'btn', act: 'new-template', cls: 'primary', icon: '➕', label: 'New',
          title: 'Empty canvas to build a new template (background, logo, text fields)' },
        { t: 'btn', act: 'save-template', icon: '💾', label: 'Save',
          title: 'Save the current template (background + logo + text fields)' },
        { t: 'link', href: '/library/studio/templates/', label: 'Manage' },
      ]},
    ]},

    { id: 'canvas', title: 'Canvas', items: [
      { t: 'row', items: [
        { t: 'label', text: 'Size' },
        { t: 'btn', act: 'canvas-size', icon: '📐', label: 'Change…', title: 'Set canvas width and height' },
      ]},
      // One place for everything about the background. There used to be a
      // second colour picker further down with the same id — it was dead code
      // and its handler overwrote this one.
      { t: 'row', items: [
        { t: 'label', text: 'Colour' },
        { t: 'color', id: 'bg-color', value: '#FBF8F0', title: 'Fill the canvas background' },
        { t: 'btn', act: 'bg-creme', label: 'Cream', title: 'Octotrial cream' },
        { t: 'btn', act: 'bg-weiss', label: 'White', title: 'White' },
        { t: 'btn', act: 'bg-transparent', label: 'None', title: 'Transparent (checkerboard)' },
      ]},
      { t: 'row', items: [
        { t: 'label', text: 'Image' },
        { t: 'btn', act: 'set-as-bg', icon: '🖼', label: 'From selection',
          title: 'Set the selected image as background – ideal for building a template' },
        { t: 'btn', act: 'clear-bg', cls: 'danger', icon: '🚫', label: 'Remove',
          title: 'Removes the background image – the background colour stays' },
      ]},
      { t: 'mount', id: 'bg-info', cls: 'bg-info' },
      { t: 'btn', act: 'clear-all', cls: 'danger', wide: true, icon: '🧹', label: 'Clear canvas',
        title: 'Remove every element from the canvas' },
    ]},

  ],

  insert: [
    { id: 'text', title: 'Text', items: [
      { t: 'text', id: 'text-input', ph: 'Enter text…', wide: true },
      { t: 'row', items: [
        { t: 'num', id: 'font-size', value: 32, min: 6, max: 400, step: 1, w: 56,
          title: 'Font size in pixels – freely adjustable' },
        { t: 'color', id: 'text-color', value: '#111111', title: 'Text colour' },
        { t: 'select', id: 'font-weight', w: 74, opts: [
          { v: 'normal', l: 'Normal' }, { v: 'bold', l: 'Bold', sel: true }] },
        { t: 'btn', act: 'add-text', cls: 'primary push', label: '+ Text' },
      ]},
      { t: 'row', items: [
        { t: 'btn', act: 'text-left',   icon: '⯇', title: 'Left align' },
        { t: 'btn', act: 'text-center', icon: '≡', title: 'Centre' },
        { t: 'btn', act: 'text-right',  icon: '⯈', title: 'Right align' },
      ]},
    ]},

    { id: 'textblock', title: 'Text block', items: [
      { t: 'hint', html: 'Heading and body as <b>one</b> object.' },
      { t: 'text', id: 'tb-head', ph: 'Heading…', wide: true },
      { t: 'area', id: 'tb-body', ph: 'Body text…', rows: 2 },
      { t: 'row', items: [
        { t: 'label', text: 'Width' },
        { t: 'num', id: 'tb-width', value: 260, min: 60, step: 10, w: 64 },
        { t: 'label', text: 'Size' },
        { t: 'num', id: 'tb-size', value: 19, min: 8, step: 1, w: 54 },
        { t: 'btn', act: 'add-textblock', cls: 'primary push', label: '+ Block' },
      ]},
      { t: 'row', items: [
        { t: 'btn', act: 'add-checktext', label: '✓ Check + text',
          title: 'Octovis check + text as ONE object. Double-click to edit, text wraps at the width.' },
        { t: 'btn', act: 'add-checklist', label: '✓✓✓ Checklist',
          title: 'Three checkmark lines as ONE object. Double-click: one line per check.' },
      ]},
    ]},

    { id: 'shapes', title: 'Shapes', items: [
      { t: 'grid', items: [
        { t: 'shape', shape: 'arrow',        icon: '➜', title: 'Arrow' },
        { t: 'shape', shape: 'line',         icon: '╱', title: 'Line' },
        { t: 'shape', shape: 'dottedLine',   icon: '┈', title: 'Dashed line' },
        { t: 'shape', shape: 'circle',       icon: '◯', title: 'Circle' },
        { t: 'shape', shape: 'filledCircle', icon: '●', title: 'Filled circle' },
        { t: 'shape', shape: 'rect',         icon: '▭', title: 'Rectangle' },
        { t: 'shape', shape: 'filledRect',   icon: '■', title: 'Filled rectangle' },
        { t: 'shape', shape: 'hex',          icon: '⬡', title: 'Hexagon (outline)' },
        { t: 'shape', shape: 'filledHex',    icon: '⬢', title: 'Hexagon (filled)' },
      ]},
    ]},

    { id: 'badges', title: 'Badges', items: [
      { t: 'hint', text: 'Click, type, Enter. Double-click to edit later.' },
      { t: 'row', items: [
        { t: 'badge', badge: 'circle', icon: '①', label: 'Circle', title: 'Circle with number or text' },
        { t: 'badge', badge: 'hex',    icon: '⬢', label: 'Hexagon', title: 'Hexagon with number or text' },
        { t: 'badge', badge: 'pill',   icon: '▭', label: 'Banner',  title: 'Banner pill with text' },
      ]},
    ]},
  ],

  // The Image panel is the big win: 11 retouch buttons become 3 tools × 3
  // scopes. `data-tool` still carries the legacy name, so studio.js needs no
  // change — ui.js rewrites the attribute when the scope changes.
  image: [
    { id: 'retouch', items: [
      { t: 'raw', html: '<div id="retouch-hint" class="placeholder-box">'
          + '<span class="big">✂</span><b>No image to work on.</b><br>'
          + 'Insert one from <b>Media</b> (right) or click an image on the canvas — '
          + 'then the tools below become active.</div>' },
      { t: 'raw', html: '<div id="retouch-body">' },   // visible by default:
      // updateRetouchPanel() in studio.js switches it, and if that boot step
      // ever fails the tools should still be there rather than a blank panel

      { t: 'raw', html: '<h4 class="group-head">Automatic</h4><div class="section-body">' },
      { t: 'btn', act: 'cutout', wide: true, icon: '✂', label: 'Remove background',
        title: 'Remove the detected background all around' },
      { t: 'btn', act: 'checker-remove', wide: true, icon: '🧩', label: 'Remove checkerboard',
        title: 'Remove only the baked-in checkerboard pattern – white content stays' },
      { t: 'raw', html: '</div>' },

      { t: 'raw', html: '<h4 class="group-head">Tool</h4><div class="section-body">' },
      { t: 'row', cls: 'tool-row', items: [
        { t: 'tool', key: 'erase',    tool: 'fill', icon: '🧽', label: 'Erase',
          title: 'Make parts of the image transparent' },
        { t: 'tool', key: 'recolour', tool: 'recolorpick', icon: '🎨', label: 'Recolour',
          title: 'Replace colour in the image' },
        { t: 'tool', key: 'select',   tool: 'rect',  icon: '🔲', label: 'Select',
          title: 'Mark an area first, then apply' },
      ]},

      // Scope only applies to Erase and Recolour; ui.js hides it for Select.
      { t: 'raw', html: '<div id="scope-row" class="scope-row">' },
      { t: 'label', text: 'Applies to' },
      { t: 'row', cls: 'seg', id: 'scope-seg', items: [
        { t: 'raw', html: '<button type="button" class="seg-btn on" data-scope="area" '
            + 'title="Click a spot in the image — that connected area becomes transparent">Click an area</button>' },
        { t: 'raw', html: '<button type="button" class="seg-btn" data-scope="brush" '
            + 'title="Drag over the image by hand">Brush</button>' },
        { t: 'raw', html: '<button type="button" class="seg-btn" data-scope="all" '
            + 'title="Click a colour — every matching area in the image goes">Whole colour</button>' },
      ]},
      { t: 'raw', html: '</div>' },

      // Select-only: shape of the marking, then what to do with it.
      { t: 'raw', html: '<div id="select-row" class="scope-row" hidden>' },
      { t: 'row', items: [
        { t: 'tool', key: 'sel-rect', tool: 'rect', icon: '🔲', label: 'Rectangle',
          title: 'Drag a rectangle over the area' },
        { t: 'tool', key: 'sel-free', tool: 'mark', icon: '✍', label: 'Free',
          title: 'Freely paint over an area in red – good for irregular shapes' },
      ]},
      { t: 'raw', html: '</div>' },

      { t: 'row', id: 'mark-apply-row', hide: true, items: [
        { t: 'mark', mark: 'remove',  cls: 'danger',  icon: '🗑', label: 'Delete area',
          title: 'Make the marked area transparent' },
        { t: 'mark', mark: 'recolor', cls: 'primary', icon: '🎨', label: 'Recolour area',
          title: 'Recolour the marked area to the colour chosen below' },
      ]},

      { t: 'row', id: 'brush-row', hide: true, items: [
        { t: 'label', text: 'Brush' },
        { t: 'range', id: 'brush-slider', min: 1, max: 100, step: 1, value: 20,
          title: 'Brush size — the lower half of the slider covers the fine sizes' },
        { t: 'raw', html: '<span id="brush-val" class="ctl-value">20 px</span>' },
      ]},

      { t: 'row', id: 'recolor-color-row', hide: true, items: [
        { t: 'label', text: 'Colour' },
        { t: 'color', id: 'recolor-color', value: '#F56E28',
          title: 'Colour for recolouring and painting – also selectable from the palette' },
        { t: 'raw', html: '<span id="recolor-swatch" class="picked-swatch" title="Picked colour"></span>' },
        { t: 'raw', html: '<span class="hint inline">picked</span>' },
      ]},

      { t: 'row', items: [
        { t: 'tool', key: 'restore', tool: 'restore', icon: '↩', label: 'Restore',
          title: 'Wipe over the image → the original comes back there' },
        { t: 'tool', key: 'off', tool: 'off', icon: '✋', label: 'Done',
          title: 'End the tool' },
      ]},
      { t: 'raw', html: '<div id="tool-status" class="tool-status"></div>' },
      { t: 'raw', html: '</div>' },   // /section-body of "Tool"
      { t: 'raw', html: '</div>' },   // /retouch-body
    ]},
  ],

  layers: [
    { id: 'layers', title: 'Elements', items: [
      { t: 'mount', id: 'layers-list', placeholder: 'No elements yet.' },
    ]},
    { id: 'order', title: 'Order', items: [
      { t: 'row', items: [
        { t: 'btn', act: 'forward',  icon: '⬆', label: 'Forward',  title: 'Bring the selection forward' },
        { t: 'btn', act: 'backward', icon: '⬇', label: 'Backward', title: 'Send the selection backward' },
      ]},
      { t: 'row', items: [
        { t: 'btn', act: 'group',   icon: '🔗', label: 'Group',   title: 'Glue selected parts into a group' },
        { t: 'btn', act: 'ungroup', icon: '✂',  label: 'Ungroup', title: 'Ungroup again' },
      ]},
      { t: 'hint', html: '🎬 Animation stays in the bar below the canvas — '
                       + 'there you see every element side by side.' },
    ]},
  ],
};

/* ---------------------------------------------------------------------------
   Right-hand media panel — one panel with tabs instead of three stacked
   sections that each scrolled separately.
   --------------------------------------------------------------------------- */

export const MEDIA_TABS = [
  { id: 'upload',  label: 'Upload' },
  { id: 'assets',  label: 'Assets' },
  { id: 'outputs', label: 'Outputs' },
];

export const MEDIA = {
  upload: [
    { t: 'btn', id: 'upload-btn', cls: 'primary', wide: true, icon: '📤', label: 'Upload image' },
    { t: 'file', id: 'upload-input', accept: 'image/*', multiple: true },
    { t: 'btn', id: 'svg-import-btn', wide: true, icon: '📐', label: 'Import SVG',
      title: 'Insert an SVG split apart: ribbons, shapes and icons become individual objects' },
    { t: 'check', id: 'svg-as-group', label: 'insert as one object' },
    { t: 'file', id: 'svg-file-input', accept: '.svg,image/svg+xml' },
    { t: 'hint', text: 'SVGs from Assets and Outputs open split apart on click.' },
    { t: 'raw', html: '<div id="upload-status" class="upload-status"></div>' },
    { t: 'mount', id: 'upload-grid', cls: 'lib-grid', placeholder: 'Loading…' },
  ],
  assets: [
    { t: 'hint', text: 'Tick folders (several, or a parent folder):' },
    { t: 'mount', id: 'lib-tree', cls: 'lib-tree', placeholder: 'Loading…' },
    { t: 'raw', html: '<input type="text" id="lib-search" class="lib-search" placeholder="Search in selection…">' },
    { t: 'mount', id: 'lib-grid', cls: 'lib-grid', placeholder: 'Tick folders to display.' },
  ],
  outputs: [
    { t: 'row', id: 'output-tabs', cls: 'seg', items: [
      { t: 'out', out: 'Images', label: 'Images', on: true },
      { t: 'out', out: 'GIFs',   label: 'GIFs' },
      { t: 'out', out: 'Videos', label: 'Videos' },
    ]},
    { t: 'mount', id: 'output-grid', cls: 'lib-grid', placeholder: 'Loading…' },
  ],
};

/* ---------------------------------------------------------------------------
   Context bar above the canvas. Rendered on every selection change from this
   list; `when(s)` decides whether a group appears. `s` is the state object
   studio.js passes in (see buildContext).
   --------------------------------------------------------------------------- */

export const CONTEXT = [
  // Undo/Redo stay at the very front of the bar above the canvas: that is the
  // one pair of buttons reached without looking, so they are labelled and
  // coloured rather than hidden among the icons.
  { id: 'history', when: () => true, html: () => `
    <button type="button" class="tbtn primary" data-act="undo"
            title="Undo the last action (Ctrl+Z)">↶ Undo</button>
    <button type="button" class="tbtn primary" data-act="redo"
            title="Redo the last undone action (Ctrl+Y)">↷ Redo</button>
    <span class="bar-sep"></span>` },

  { id: 'who', when: s => s.hasSel,
    html: s => `<span class="sel-active" title="Active element">${esc(s.label)}</span>` },

  { id: 'size', when: s => s.hasSel, html: s => `
    <span class="sel-size" title="Size in pixels${s.count > 1 ? ' – applies to all selected elements' : ''}">
      W <input type="number" id="sel-w" class="sel-num" min="1" step="1" value="${esc(s.w)}">
      H <input type="number" id="sel-h" class="sel-num" min="1" step="1" value="${esc(s.h)}">
      <button type="button" class="tbtn" id="sel-lock" title="${s.keepRatio
        ? 'Aspect ratio locked – click to unlock' : 'Width and height free – click to lock'}"
        >${s.keepRatio ? '🔗' : '🔓'}</button>
    </span>` },

  { id: 'pos', when: s => s.hasSel, html: s => `
    <span class="sel-size" title="Centre point in pixels${s.count > 1 ? ' – puts them all in the same place' : ''}">
      X <input type="number" id="sel-x" class="sel-num" step="1" value="${esc(s.x)}">
      Y <input type="number" id="sel-y" class="sel-num" step="1" value="${esc(s.y)}">
    </span>` },

  { id: 'distribute', when: s => s.count > 1, html: () => `
    <span class="sel-size" title="Match and distribute">
      <button type="button" class="tbtn" id="same-size" title="Make all the size of the first selected">⧉</button>
      <button type="button" class="tbtn" id="dist-h" title="Distribute evenly horizontally">↔≡</button>
      <button type="button" class="tbtn" id="dist-v" title="Distribute evenly vertically">↕≡</button>
    </span>` },

  { id: 'arrange', when: s => s.hasSel, items: [
    { t: 'sep' },
    { t: 'btn', act: 'duplicate', icon: '📋', title: 'Duplicate (Ctrl+D)' },
    { t: 'btn', act: 'flip-h',    icon: '↔',  title: 'Flip horizontally' },
    { t: 'btn', act: 'flip-v',    icon: '↕',  title: 'Flip vertically' },
    { t: 'btn', act: 'forward',   icon: '⬆',  title: 'Bring forward' },
    { t: 'btn', act: 'backward',  icon: '⬇',  title: 'Send backward' },
  ]},

  { id: 'group',   when: s => s.count > 1,
    items: [{ t: 'btn', act: 'group', icon: '🔗', label: 'Group', title: 'Glue selected parts into a group' }] },
  { id: 'split-checklist', when: s => s.isChecklist,
    items: [{ t: 'btn', act: 'split-checklist', icon: '↕', label: 'Split rows',
              title: 'Turn every line of the checklist into an element of its own, so each can fly in at its own time. Positions stay put.' }] },
  { id: 'ungroup', when: s => s.isGroup,
    items: [{ t: 'btn', act: 'ungroup', icon: '✂', label: 'Ungroup', title: 'Ungroup again' }] },

  { id: 'align', when: s => s.hasSel, items: [
    { t: 'sep' },
    { t: 'btn', act: 'align-left',    icon: '⬅',  title: 'Align left' },
    { t: 'btn', act: 'align-centerH', icon: '↔|', title: 'Centre horizontally' },
    { t: 'btn', act: 'align-right',   icon: '➡',  title: 'Align right' },
    { t: 'btn', act: 'align-top',     icon: '⬆|', title: 'Align top' },
    { t: 'btn', act: 'align-centerV', icon: '↕|', title: 'Centre vertically' },
    { t: 'btn', act: 'align-bottom',  icon: '⬇|', title: 'Align bottom' },
    { t: 'sep' },
    { t: 'btn', act: 'delete', cls: 'danger', icon: '🗑', title: 'Delete (Del)' },
  ]},

  { id: 'empty', when: s => !s.hasSel,
    html: () => '<span class="hint inline">Nothing selected — pick an element, '
              + 'or drag an image in from Media.</span>' },

  // Always visible: view controls belong to the canvas, not to a selection.
  { id: 'view', when: () => true, html: s => `
    <span class="bar-gap"></span>
    <button type="button" class="tbtn${s.gridOn ? ' primary' : ''}" data-act="grid"
            title="Show/hide the alignment grid (not saved)">▦</button>
    <button type="button" class="tbtn" data-act="zoom-out" title="Zoom out">🔍−</button>
    <button type="button" class="tbtn" data-act="zoom-reset" title="Reset zoom">⤢</button>
    <button type="button" class="tbtn" data-act="zoom-in" title="Zoom in">🔍+</button>
    <button type="button" class="tbtn${s.maxi ? ' primary' : ''}" data-act="maximize"
            title="Large canvas: bars hidden, canvas fills the screen">⛶</button>` },
];

/* ---------------------------------------------------------------------------
   Public builders
   --------------------------------------------------------------------------- */

export function buildRail() {
  // Help is not a mode: it opens the guide. So it sits set apart below the four
  // modes and carries data-help instead of data-mode. In the page header nobody
  // found it.
  return MODES.map((m, i) =>
    `<button type="button" class="rail-btn${i === 0 ? ' active' : ''}" data-mode="${m.id}"`
    + attr('title', m.title) + `><span class="ico">${esc(m.icon)}</span>${esc(m.label)}</button>`).join('')
    + '<div class="rail-sep"></div>'
    + '<button type="button" class="rail-btn rail-help" data-help="1" '
    + 'title="Open the user guide"><span class="ico">📖</span>Help</button>';
}

export function buildPanels() {
  return Object.entries(PANELS).map(([mode, sections]) =>
    `<div class="mode-panel" data-panel="${mode}"${mode === 'build' ? '' : ' hidden'}>`
    + sections.map(renderSection).join('') + '</div>').join('');
}

export function buildMediaTabs() {
  return MEDIA_TABS.map((t, i) =>
    `<button type="button" class="seg-btn${i === 0 ? ' on' : ''}" data-media="${t.id}">${esc(t.label)}</button>`
  ).join('');
}

export function buildMedia() {
  return Object.entries(MEDIA).map(([tab, items]) =>
    `<div class="media-panel" data-media-panel="${tab}"${tab === 'upload' ? '' : ' hidden'}>`
    + items.map(renderItem).join('') + '</div>').join('');
}

export function buildContext(state) {
  return CONTEXT
    .filter(g => !g.when || g.when(state))
    .map(g => g.html ? g.html(state) : g.items.map(renderItem).join(''))
    .join('');
}

export const MODE_TITLES = Object.fromEntries(MODES.map(m => [m.id, m.label]));
