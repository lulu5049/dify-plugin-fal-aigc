# 在 GitHub 上建立独立插件仓库并一键打包

仓库建议名称：`dify-plugin-fal-aigc`（所有者 `lulu5049`）。

1. 打开 https://github.com/new?name=dify-plugin-fal-aigc 并建立**空的** Public 仓库（不要勾选初始化 README）。
2. 解压 `fal_aigc_0.2.0_source.zip`，确保 `manifest.yaml` 位于解压目录根目录。
3. 在该目录执行：

```bash
git init -b main
git add .
git commit -m "Add Fal AIGC Dify plugin v0.2.0"
git remote add origin https://github.com/lulu5049/dify-plugin-fal-aigc.git
git push -u origin main
```

4. 进入 GitHub 仓库：**Actions → Build Dify Plugin → Run workflow**。
5. 在该 Action 的运行详情底部的 **Artifacts** 下载 `fal_aigc_0.2.0-difypkg`，解压 Action artifact ZIP，得到真正由 Dify CLI 生成的 `fal_aigc_0.2.0.difypkg`。
6. 将 `.difypkg` 在 Dify 的 Plugins → Install Plugin → Local File 中导入。

注意：这里的本地 `.difypkg` 文件是按 Dify 插件格式手工构建的 ZIP，仅作试装包，尚未通过官方 CLI 验证；推荐 GitHub Actions 产出的版本。
