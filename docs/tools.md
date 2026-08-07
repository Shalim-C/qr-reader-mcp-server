# 工具参考

## `decode_qrcode_full`

### 用途

全图二维码检测与解码。返回所有检测到的码 + 图像质量详情。

### AI 助手应在何时使用

1. 首次尝试——在任何增强操作之前先调用此工具
2. 确认已成功解码的结果
3. 扫描未知二维码位置的图片
4. 单张图中检测多个二维码

### 输入 Schema

```json
{
  "type": "object",
  "properties": {
    "image_path": {
      "type": "string",
      "description": "本地图片绝对路径（推荐）——传文件路径而非 base64，避免 stdio 管道传输大体积数据超时"
    },
    "image_base64": {
      "type": "string",
      "description": "Base64 编码的 PNG/JPEG 图片"
    },
    "image_url": {
      "type": "string",
      "description": "可公开访问的图片 URL"
    }
  }
}
```

`image_path`、`image_base64` 和 `image_url` 至少提供一个。`image_path` 为首选。

### 输出字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `success` | boolean | 至少解码出一个二维码时为 `true` |
| `result_code` | string | 五类结果码之一 |
| `results` | array | 解码结果数组（仅成功时） |
| `results[].content` | string\|null | 解码文本内容 |
| `results[].bbox` | [int,int,int,int] | 二维码坐标 `[x, y, width, height]` |
| `results[].type` | string | 始终为 `"QRCODE"` |
| `results[].raw_bytes` | string | 十六进制原始字节 |
| `results[].result_code` | string | 逐码结果码（多码场景） |
| `results[].warning` | string | 警告类型（当 `SUCCESS_WITH_WARNING` 时） |
| `analysis` | object | 质量指标和问题分类 |
| `analysis.total_detected` | int | 检测到的二维码数量 |
| `analysis.quality` | object | `blur_score`、`contrast`、`glare_ratio`、`noise_level` |
| `analysis.primary_issue` | string | 失败根因（`too_blur`、`too_dark`、`glare`、`low_contrast`、`no_qr`、`invalid_encoding`） |
| `suggestion` | string\|null | 人类可读的修复建议 |

### 错误返回

```json
{
  "error": {
    "code": "IMAGE_LOAD_FAILED",
    "message": "图片加载失败：..."
  }
}
```

---

## `enhance_and_decode`

### 用途

裁剪图片指定区域，执行增强操作，然后尝试解码。

### AI 助手应在何时使用

1. `decode_qrcode_full` 返回 `RETRYABLE`——详情信息告诉了你失败原因
2. 你已知二维码的大致位置（使用上次返回的 `bbox`）
3. 想对偏小的二维码放大、模糊的边缘锐化等

### 输入 Schema

```json
{
  "type": "object",
  "properties": {
    "image_path": { "type": "string" },
    "image_base64": { "type": "string" },
    "image_url": { "type": "string" },
    "bbox": {
      "type": "array",
      "items": { "type": "integer" },
      "description": "原图中的目标区域 [x, y, width, height]"
    },
    "operations": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "op": {
            "type": "string",
            "enum": ["upscale", "sharpen", "adjust_contrast", "denoise"]
          },
          "params": { "type": "object" }
        },
        "required": ["op"]
      }
    }
  },
  "required": ["bbox"]
}
```

### 增强操作参考

| 操作 | 适用场景 | 关键参数 | 建议范围 |
|---|---|---|---|
| `upscale` | 小尺寸或低分辨率二维码 | `scale` | 1.5–4.0 |
| `sharpen` | 轻微模糊的边缘 | `strength` | 1.0–3.0 |
| `adjust_contrast` | 低对比度 / 打印褪色 | `alpha` | 0.5–3.0 |
| `denoise` | 噪点多的照片 | `h` | 5–30 |

### AI 决策流程

```
analysis.primary_issue = "too_blur"（太模糊）
  → upscale (scale=2.0–3.0) + sharpen (strength=1.5–2.0)

analysis.primary_issue = "glare"（反光）
  → adjust_contrast (alpha=0.8)  // 压低高光

analysis.primary_issue = "low_contrast"（对比度不足）
  → adjust_contrast (alpha=2.0–3.0)

analysis.primary_issue = "too_dark"（太暗）
  → adjust_contrast (alpha=2.0, beta=30) + denoise
```

### 输出字段

与 `decode_qrcode_full` 相同，额外增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| `applied_operations` | string[] | 实际执行的操作列表 |

### 错误返回

```json
{
  "error": {
    "code": "READ_ONLY_MODE",
    "message": "enhance_and_decode 在只读模式下不可用"
  }
}
```
