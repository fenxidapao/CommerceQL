// Design Token —— 唯一来源：docs/06_UIUX设计文档.md §3.7（文档内嵌交付，逐字复制）
// 深色模式扩展位已预留（P0 不实现，见 06 §1.3 / B-17）

export const tokens = {
  color: {
    brand:    { bg: '#E6F1FB', border: '#185FA5', text: '#042C53', solid: '#185FA5' },
    refuse:   { bg: '#F1EFE8', border: '#B4B2A9', text: '#2C2C2A' },
    degraded: { bg: '#FAEEDA', border: '#BA7517', text: '#412402' },
    error:    { bg: '#FCEBEB', border: '#A32D2D', text: '#501313' },
    success:  { bg: '#EAF3DE', border: '#3B6D11', text: '#173404' },
    info:     { bg: '#E6F1FB', border: '#378ADD', text: '#042C53' },
    clarify:  { bg: '#EEEDFE', border: '#534AB7', text: '#26215C' },
    neutral:  { bg: '#F1EFE8', border: '#D3D1C7', text: '#5F5E5A' },
    text:     { primary: '#2C2C2A', secondary: '#5F5E5A', tertiary: '#888780' },
    chart:    { up: '#A32D2D', down: '#3B6D11', flat: '#185FA5',
                series: ['#185FA5','#534AB7','#0F6E56','#BA7517','#993556','#5F5E5A'] },
  },

  space: { xxs: 4, xs: 8, sm: 12, md: 16, lg: 24, xl: 32, xxl: 48 },

  radius: { sm: 4, md: 8, lg: 12, xl: 16, full: 999 },

  font: {
    size: { h1: 20, h2: 16, h3: 14, body: 13, caption: 12, kpi: 28, mono: 12.5 },
    lineHeight: { h1: 28, h2: 24, h3: 22, body: 22, caption: 20, mono: 20 },
    weight: { regular: 400, medium: 500 },
  },

  shadow: {
    raise:   '0 1px 2px rgba(0,0,0,0.06)',
    overlay: '0 6px 16px rgba(0,0,0,0.08)',
  },

  z: { base: 0, sticky: 10, drawer: 100, dropdown: 1000, modal: 1010, toast: 1080 },

  size: {
    header: 56, sessionRail: 240, sessionRailCollapsed: 56,
    detailDrawer: 424, askBoxMin: 88, stageBar: 40,
  },
} as const;

// Ant Design 5 theme 映射
export const antdTheme: import('antd').ThemeConfig = {
  token: {
    colorPrimary: tokens.color.brand.solid,
    colorError: tokens.color.error.border,
    colorWarning: tokens.color.degraded.border,
    colorSuccess: tokens.color.success.border,
    colorInfo: tokens.color.info.border,
    colorText: tokens.color.text.primary,
    colorTextSecondary: tokens.color.text.secondary,
    colorTextTertiary: tokens.color.text.tertiary,
    borderRadius: tokens.radius.md,
    borderRadiusLG: tokens.radius.lg,
    fontSize: tokens.font.size.body,
    fontFamily: [
      '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"PingFang SC"',
      '"Hiragino Sans GB"', '"Microsoft YaHei"', '"Helvetica Neue"', 'Arial', 'sans-serif',
    ].join(', '),
    controlHeight: 32,
    wireframe: false,
  },
  components: {
    Table: { headerBg: tokens.color.neutral.bg, cellPaddingBlockSM: 8, cellPaddingInlineSM: 12 },
    Card:  { paddingLG: tokens.space.md },
    Alert: { defaultPadding: `${tokens.space.xs}px ${tokens.space.sm}px` },
    Drawer:{ paddingLG: tokens.space.md },
  },
};
