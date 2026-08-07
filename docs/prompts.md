# Agent 行为指南（写给 AI 模型看的）

接入 QR Reader MCP Server 后，你会获得三个工具：`decode_qrcode_full`、`enhance_and_decode` 和 `auto_enhance`。以下是你的行为准则。

## 触发时机

| 你的能力 | 何时触发 |
|----------|----------|
| 多模态模型（能看图） | 看到用户提供的图片中有二维码 → **主动调用** `decode_qrcode_full`，不等用户说"帮我扫" |
| 纯文本模型 | 用户给了图片路径/URL 并提到"扫码""二维码"等词 → 调用 `decode_qrcode_full` |

## 收到返回后——按 result_code 决策

### `SUCCESS`
解码成功，内容在 `results[].content`。**直接告诉用户内容，不废话。**
多码图片时逐条列出，附上位置信息（`bbox`）。

### `SUCCESS_WITH_WARNING`
内容取到了但可能有异常（空内容、乱码、控制字符）。
把内容和警告一起告诉用户，让他确认是否正确。

### `RETRYABLE`
关键字段：`analysis.primary_issue` 和 `analysis.quality`。
解码失败但**可修复**——根据 issue 类型选择增强策略，调用 `enhance_and_decode`：

| primary_issue | 增强操作 |
|--------------|---------|
| `blur` | `[{"op":"sharpen","params":{"strength":2.0}}]` + 可叠 `upscale` |
| `glare` | `[{"op":"adjust_contrast","params":{"alpha":2.0}}]` + 提示用户换角度 |
| `low_contrast` | `[{"op":"adjust_contrast","params":{"alpha":2.5}}]` |
| `unknown`（light mode） | 先试 `[{"op":"upscale","params":{"scale":2.0}},{"op":"sharpen","params":{"strength":2.0}}]` |

增强后仍失败 → 把 `suggestion` 翻译成自然语言告诉用户。

### `NO_QR_FOUND`
图片中没找到二维码。把 `analysis.primary_issue` 和 `suggestion` 翻译成自然语言告诉用户。
- `too_blur` → "图片太模糊了，换个角度拍"
- `too_dark` → "光线不够，开灯或换个亮的地方"
- `no_qr` → "图片里没有二维码"

### `QR_UNRECOVERABLE`
二维码找到了但**无法解码**。告诉用户二维码可能损坏，或使用了不支持的编码格式。

## 增强操作的组合顺序

有效的组合模式：
- **太小看不清**：`upscale → sharpen`
- **模糊**：`sharpen` 单用或叠 `upscale`
- **太暗/对比度低**：`adjust_contrast` 单用
- **噪点多**：`denoise → sharpen`

最多 5 步，参数会被自动 clamp 到安全范围，不需要手动算。

## 批量处理

多张图片时每张独立调用 `decode_qrcode_full`。单张内多个二维码不需要额外操作——一次调用返回全部。
失败的重试用同一流程，不要合并不同图片的结果。
