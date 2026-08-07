# 故障排查

## 常见问题

### "ModuleNotFoundError: No module named 'pyzbar'"

pyzbar 需要系统安装 ZBar 库：

```bash
# Ubuntu/Debian
sudo apt install libzbar0

# macOS
brew install zbar

# Windows
choco install zbar
```

### "ImportError: Unable to find zbar shared library"

Windows 上通过 vcpkg 安装 zbar 后，需要设置 `ZBAR_PATH` 环境变量：

```cmd
set ZBAR_PATH=C:\path\to\vcpkg\installed\x64-windows\bin
```

或将 `libzbar-64.dll`（或 `libzbar-32.dll`）复制到 Python DLL 目录或项目根目录。

### "IMAGE_LOAD_FAILED"（图片加载失败）

服务器无法解码图片数据。可能原因：

1. **Base64 格式错误**——确保是纯 base64 字符串，不含换行符
2. **URL 无法访问**——检查 URL 和网络连接
3. **图片超出 `MAX_IMAGE_SIZE`**——调高上限或使用更小的图片

### "READ_ONLY_MODE" 错误

在只读模式下调用了 `enhance_and_decode`。解决方法：

1. 设置 `READ_ONLY_MODE=false` 后重启
2. 改用 `decode_qrcode_full`（`auto_enhance` 和 `enhance_and_decode` 在只读模式下均不可用）

### 每张图都返回 "NO_QR_FOUND"

查看详情信息：

- `primary_issue: too_blur` → 图片太模糊，让用户重新拍摄
- `primary_issue: too_dark` → 对比度过低，建议调整光线
- `primary_issue: no_qr` → 图中确实没有二维码，确认图片内容

### "RETRYABLE" 循环——增强后仍然失败

每次工具调用独立分类，不会自动进行状态迁移。推荐做法：

1. **首选 `auto_enhance`**：一次调用自动尝试 7 种增强策略，首次成功即返回
2. 如果 `auto_enhance` 全部 7 策略均失败，建议用户重新拍摄（防抖、调整光线）
3. `enhance_and_decode` 仅适合需要精确控制增强策略的场景

### 服务启动了但 MCP 客户端连不上

1. 确认 Python 3.10+：`python --version`
2. 确认包已安装：`pip list | grep qr-reader`
3. 检查客户端配置——命令应为 `python -m qr_reader.server`
4. 尝试独立运行：`python -m qr_reader.server`（不应报错）

### 开启调试日志

设置 `LOG_LEVEL=debug` 查看详细日志：

```json
{
  "mcpServers": {
    "qr-reader": {
      "command": "python",
      "args": ["-m", "qr_reader.server"],
      "env": {
        "LOG_LEVEL": "debug"
      }
    }
  }
}
```
