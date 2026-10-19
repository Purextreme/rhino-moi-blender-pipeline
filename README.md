# Rhino MoI Blender Pipeline

用于 Codex 的 Rhino → MoI → Blender 管线 Skill。读取当前 Rhino 文档，生成独立 Rhino 5 工作副本，经 MoI 网格化为 FBX，再导入已打开的 Blender。

## 能力

- 保留 Rhino 源文档和 Blender 已有场景。
- 根据源对象身份、块实例和包围盒核对导入结果，验证物理比例及自定义法线。
- 将图层和嵌套块重建为 Empty 父子层级，用一个集合打包模型，省略没有导入对象的空图层分支。
- 默认烘焙对象缩放；所有网格共用世界原点轴心时，将各自轴心移到包围盒中心，保留层级、世界形状、法线和 UV 控制器效果。
- 后处理检查法线朝向；开口面、内腔等无法可靠判断的对象会明确提示，不自动重算法线。
- 将法线反向或待确认的对象额外链接到分类检查集合，保留原集合和父子关系，方便集中复核。
- 用户提供外观参考图、商品链接或贴图时，顺带完成简单预览材质、纹理映射和视觉检查；没有提供时跳过，在完成后可询问一次。
- 对转换与材质处理分别验收，保留原有转换证据。

## 运行条件

- Windows、PowerShell，以及已打开的 Rhino 7、MoI 和 Blender。
- Blender MCP 已连接，可以读取并执行当前 Blender 场景中的操作。
- `blender-playbook` Skill：本管线使用的 Blender 操作与验证依赖，未包含在本仓库内。
- 操作 MoI 对话框时需要可用的 Computer Use 能力，或经过当前版本验证的应用脚本接口。

本仓库是 Skill 和辅助脚本，不是独立的 Blender 插件或一键转换程序。Cinema 4D 不是依赖。

## 安装与使用

把仓库克隆到 Codex 的 Skills 目录；如果目标目录已经存在，先检查现有内容，不要覆盖本地修改。

```powershell
git clone https://github.com/Purextreme/rhino-moi-blender-pipeline.git "$env:USERPROFILE\.codex\skills\rhino-moi-blender-pipeline"
```

然后在 Codex 中调用：

```text
使用 $rhino-moi-blender-pipeline，把当前 Rhino 模型经 MoI 导入已打开的 Blender。
```

需要预览材质时，可以在同一请求中附上产品参考图、商品链接或本地贴图目录。具体流程、验证与恢复规则见 [SKILL.md](SKILL.md)。

## 范围与文件

工作副本支持 Brep，以及可转为 Brep 的 Surface / Extrusion。曲线和点会明确记录为未导入；其他未支持的可网格化类型会停止处理，避免静默丢失。不会默认合并网格、重算法线或修改原始 CAD 几何。

- [references/workflow.md](references/workflow.md)：完整流程。
- [references/blender-operations.md](references/blender-operations.md)：Blender 脚本调用与验收边界。
- [references/post-processing.md](references/post-processing.md)：缩放、轴心及法线朝向后处理。
- [references/preview-materials.md](references/preview-materials.md)：可选预览材质流程。
- `scripts/rhino-metadata/`：Rhino 元数据和独立工作副本导出。
- `scripts/blender_pipeline.py`：导入、诊断、规划、层级重建和转换验证。
- `scripts/blender_cleanup.py`、`scripts/blender_normals_audit.py`：默认后处理及独立验收。

可用 Blender 后台运行回归验证：

```powershell
& '<Blender 安装目录>\blender.exe' --background --factory-startup --python-exit-code 1 --python tests/test_post_processing.py
```

模型、贴图、机器本地配置、临时文件和案例数据不包含在仓库中。最终 `.blend` 的保存位置由用户决定。
