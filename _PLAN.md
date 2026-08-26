# 照片调色 Skill 分阶段扩展实施计划

## 1. 摘要

本计划以当前 `develop`/`main` 指向的提交 `e2a8444` 为基线，保持确定性、非生成式 JPEG/PNG 调色、现有 CLI、JSON 报告字段、尺寸、alpha 和适用元数据行为。

核心兼容策略：

- 继续使用 `schema_version: 1`，所有新增能力均为可选字段，省略时走现有实现。
- 不改变旧 `curve` 的结构或语义；新增独立的 `channel_curves`。
- 旧配方的 8 位处理、旧蒙版、旧色彩算法、旧降噪和锐化必须保持解码像素级回归一致。
- 新感知色彩、高位深、LUT 和高级细节处理只由新增字段显式启用。
- `SKILL.md` 只更新 Agent 决策、工作流和验收要求；完整参数结构继续集中在 `references/parameters.md`。

## 2. 当前实现摘要与真实缺口

### 2.1 仓库现状

当前受版本控制的功能文件只有：

- `SKILL.md`
- `references/parameters.md`
- `scripts/photo_grade.py`
- `README.md`
- `update.py`
- `agents/openai.yaml`
- `assets/icon.svg`
- `.github/workflows/publish-skill.yml`

没有已提交的测试、测试配置、示例图片、示例配方或依赖清单。发布工作流直接打包并发布，没有测试门禁。Skill 在 UTF-8 环境下通过现有 `quick_validate.py`。

### 2.2 实际 schema、CLI 与报告

配方严格要求五个顶层键：

- `schema_version`
- `style`
- `visual_intent`
- `success_criteria`
- `parameters`

当前仅接受 `schema_version: 1`；未知字段全部拒绝。`parameters` 支持：

- `basic`
- `curve`
- `hsl`
- `color_grading`
- `local_corrections`
- `local_adjustments`
- `detail`
- `output`

CLI 只有：

- `analyze <input> [--pretty]`
- `grade <input> <output> --recipe <json> [--show-parameters] [--skip-update-check] [--pretty]`
- `compare <original> <graded> [--pretty]`

必须保持这些命令和现有参数有效，不增加新的必填 CLI 参数。

现有报告：

- `analyze`：文件、格式、尺寸、alpha 和 `metrics`。
- `grade`：输入输出路径、尺寸、样式、`recipe_validated`、`before`、`after`，可选展开参数与更新消息。
- `compare`：两侧分析结果及尺寸、alpha 存在性、alpha 值检查。

后续只能增加字段，不能删除、重命名或改变现有字段类型。

### 2.3 真实处理管线

代码实际顺序为：

1. Pillow 解码并转换为 `RGB`/`RGBA`。
2. 有 ICC 时尝试通过 LittleCMS 转为 sRGB；失败被静默忽略。
3. 转为 `float32`，但此时 RGB/alpha 已是 8 位精度。
4. 可选 3×3 RGB 中值滤波混合。
5. 在线性 sRGB 中依次执行白平衡、曝光。
6. 返回编码 sRGB，以亮度蒙版同时计算高光、阴影、白色和黑色，再执行对比度。
7. 应用现有主曲线。
8. 应用 `local_corrections`。
9. 自然饱和度和整体饱和度。
10. HSV 选择性 HSL。
11. sRGB 色度向量式三向调色。
12. 应用 `local_adjustments`。
13. RGB 非锐化蒙版。
14. 硬裁剪至 `[0,1]`，量化为 8 位并编码。
15. 重新打开输出，检查尺寸和 alpha。

README 将高光、阴影、白色、黑色描述成顺序阶段，但代码实际在同一个亮度目标中合成后再做对比度。

### 2.4 能力判定

| 目标           | 当前状态   | 真实限制与不可替代收益                                       |
| -------------- | ---------- | ------------------------------------------------------------ |
| 主曲线         | 已存在     | 在编码 sRGB 上映射亮度，再按比例缩放 RGB；是分段线性亮度曲线，不是逐通道曲线 |
| R/G/B 通道曲线 | 缺失       | HSL、白平衡和三向调色不能替代逐通道端点、阴影偏色和通道对比塑形 |
| 通道分析       | 部分存在   | 只有 RGB 均值、中性候选均值和“任一通道”裁切比例；没有逐通道直方图、百分位、独立裁切或空间通道分布 |
| 组合蒙版       | 缺失       | 单叶蒙版已有 `invert` 和 `opacity`；多个局部调整顺序叠加不等价于 AND/OR/Subtract |
| 清晰度/纹理    | 缺失       | 当前锐化是最终像素尺度 RGB unsharp，不能替代中频清晰度和较细尺度纹理 |
| 去朦胧         | 缺失       | 曝光、对比度和饱和度只能粗略模拟，无法同时处理低频雾感、黑位和色彩恢复 |
| 感知色彩       | 缺失       | 当前 HSV/sRGB 算法具备亮度缩放和肤色权重，但不是感知均匀空间 |
| 色域保护       | 部分存在   | 多处局部硬裁剪及最终 `clip`，没有色相保持的色域压缩；可能产生色相漂移或通道断裂 |
| 16 位 PNG      | 缺失       | Pillow 明确不支持每通道大于 8 位的多通道内部模式，[官方文档](https://pillow.readthedocs.io/en/stable/handbook/concepts.html)；当前输入和输出都会进入 8 位 RGB/RGBA |
| 8 位抖动       | 缺失       | 直接四舍五入，没有抖动                                       |
| RGB 原色校准   | 缺失       | 白平衡、HSL 不等价于保持中性轴的全局原色基变换               |
| 3D LUT         | 缺失       | 没有解析、验证或插值支持                                     |
| 降噪           | 粗略存在   | RGB 3×3 中值混合，经过 8 位中间图；无法独立处理亮度和色度    |
| 锐化           | 部分存在   | 有 amount/radius；没有阈值、边缘保护，模糊层经过 8 位量化    |
| ICC/元数据     | 部分存在   | 成功时归一到 sRGB；失败时继续按 sRGB 数学处理并可能重新附上原 ICC。保留 ICC、EXIF、DPI 和 PNG 文本，但不完整保留所有 PNG 色彩块 |
| 旧配方确定性   | 环境内成立 | 未固定依赖版本；JPEG 编码字节级结果可能随 Pillow/libjpeg 版本变化 |

另有一个现有代码/文档差异：HSL 饱和度验证允许到 `+1.5`，但旧执行路径对单个色相范围的有效值裁到 `+1.0`。为兼容旧结果，不应直接改变旧路径；感知色彩新路径可完整支持文档范围。

## 3. 推荐的最终处理管线

| 顺序 | 阶段                              | 空间/编码                    | 说明                                                         |
| ---: | --------------------------------- | ---------------------------- | ------------------------------------------------------------ |
|    1 | 解码、元数据与 alpha 分离         | 原文件编码                   | 旧路径保持 Pillow 8 位解码；高精度 sRGB PNG 可选择 16 位读取 |
|    2 | ICC 归一化                        | 编码 sRGB                    | 旧路径保持现状；新感知/高精度路径要求明确成功、明确 sRGB 或给出可操作错误 |
|    3 | 前置降噪                          | OKLab 或旧 RGB               | 旧 `denoise` 保持原 3×3 中值；新亮度/色度降噪在 OKLab 中边缘感知处理 |
|    4 | RGB 原色校准                      | 线性 sRGB                    | 仅全局；保持中性轴，位于白平衡前                             |
|    5 | 白平衡、曝光                      | 线性 sRGB                    | 保持当前顺序                                                 |
|    6 | 高光、阴影、白色、黑色、对比度    | 编码 sRGB                    | 旧算法不改                                                   |
|    7 | 主曲线                            | 编码 sRGB 亮度               | 现有 `curve` 原样保留                                        |
|    8 | R/G/B 通道曲线                    | 编码 sRGB 通道值             | 主曲线之后逐通道映射；未提供时完全跳过                       |
|    9 | 校正型局部调整                    | 当前阶段 RGB                 | 每个调整项按顺序执行；组合蒙版的子节点读取同一阶段快照       |
|   10 | 去朦胧、清晰度、纹理              | 感知亮度/多尺度分解          | 按低频、中频、高频顺序；先做全局存在感，再进入颜色塑形       |
|   11 | 自然饱和度、饱和度、HSL、三向调色 | 旧 sRGB/HSV 或新 OKLab/OKLCh | 由 `color_management.rendering` 选择；旧配方走原路径         |
|   12 | 色域边界处理                      | 线性 sRGB + OKLCh            | LUT 前必须得到有限、可定义的 `[0,1]` 输入                    |
|   13 | 3D LUT                            | 编码 sRGB                    | 固定 tetrahedral 插值；按 `.cube` 域映射                     |
|   14 | LUT 后色域处理                    | 线性 sRGB + OKLCh            | 压缩 LUT 产生的越界                                          |
|   15 | 创意型局部调整                    | 当前阶段 RGB                 | 让最终 dodge/burn、局部色彩和局部清晰度不被 LUT 再次扭曲     |
|   16 | 最终色域处理                      | 线性 sRGB + OKLCh            | 输出前最后一次有限值和色域保证                               |
|   17 | 输出锐化                          | RGB，边缘权重来自亮度        | 保持旧锐化路径；新阈值和保护只修改锐化增量权重               |
|   18 | 抖动、量化与编码                  | 编码 sRGB                    | 8 位 PNG 可选确定性 TPDF；16 位 PNG 不抖动；alpha 不参与抖动 |
|   19 | 重开验证与报告                    | 编码输出                     | 检查格式、位深、尺寸、alpha、有限值、报告指标                |

所有空间滤波只改变像素值，不改变尺寸、坐标、裁切或 alpha。

## 4. Schema、CLI 与兼容策略

### 4.1 Schema v1 加法扩展

保留 `curve` 作为唯一主曲线，新增以下可选段：

```json
{
  "parameters": {
    "channel_curves": {
      "red": [],
      "green": [],
      "blue": []
    },
    "presence": {
      "dehaze": 0,
      "clarity": 0,
      "texture": 0
    },
    "color_management": {
      "rendering": "legacy",
      "gamut_mapping": "clip"
    },
    "rgb_primaries": {
      "red": {"hue": 0, "saturation": 0},
      "green": {"hue": 0, "saturation": 0},
      "blue": {"hue": 0, "saturation": 0}
    },
    "lut_3d": {
      "path": "look.cube",
      "strength": 1
    },
    "detail": {
      "denoise_luminance": 0,
      "denoise_chroma": 0,
      "sharpen_threshold": 0,
      "sharpen_edge_protection": 0
    },
    "output": {
      "png_bit_depth": 8,
      "png_dither": "none"
    }
  }
}
```

约束：

- 所有新增段省略时为中性；不能仅因配方仍是 v1 就自动启用新算法。
- `channel_curves` 使用与现有曲线相同的点验证。
- `rendering` 只接受 `legacy`、`perceptual`。
- `gamut_mapping` 只接受 `clip`、`oklch_compress`。
- `png_bit_depth` 只接受 `8`、`16`；16 位只允许 PNG 输出。
- `png_dither` 只接受 `none`、`tpdf`，且仅允许 8 位 PNG。
- 旧 `denoise` 与新亮度/色度降噪不得同时为非零，避免重复滑块和不明确的叠加。
- LUT 段存在时必须同时提供有效 `path` 和 `strength`，即使强度为零也完成文件验证。
- 不引入 `schema_version: 2`；只有未来必须改变旧字段语义时再提出 v2。

### 4.2 组合蒙版结构

旧叶节点结构保持不变。新增复合节点：

```json
{
  "type": "composite",
  "operation": "and",
  "inputs": [
    {"type": "luminance", "...": "..."},
    {"type": "radial", "...": "..."}
  ],
  "opacity": 1,
  "invert": false
}
```

确定语义：

- `and`：逐像素 `min`，2–8 个输入。
- `or`：逐像素 `max`，2–8 个输入。
- `subtract`：严格两个输入，`clip(A - B, 0, 1)`；更多减法通过显式嵌套表达。
- 每个叶节点先执行自身反选和透明度；复合节点完成运算后再执行自身反选和透明度。
- 最大嵌套深度 6，最多 32 个叶节点。
- 所有子节点基于同一张阶段输入图计算，避免兄弟节点因计算顺序得到不同颜色/亮度选择。
- 不增加独立 `invert` 运算符，现有布尔字段已足够。

### 4.3 局部可用性

| 能力                  | 局部蒙版中使用                                            |
| --------------------- | --------------------------------------------------------- |
| 主曲线                | 保持现有支持                                              |
| R/G/B 通道曲线        | 允许，顺序为局部主曲线之后                                |
| 组合蒙版              | 本身就是局部选择结构                                      |
| 清晰度、纹理          | 允许                                                      |
| 去朦胧                | 不允许；低频空气光估计和局部混合容易产生接缝              |
| 感知颜色/HSL/三向调色 | 继续通过局部 basic 色彩控制使用，不增加第二套局部感知滑块 |
| 色域映射              | 不作为滑块使用；在局部结果混合后统一保护                  |
| RGB 原色校准          | 不允许；它是全局输入基变换                                |
| 3D LUT                | 不允许；v1 只允许一个全局 LUT                             |
| 降噪、输出锐化        | 不允许；避免蒙版边界纹理不连续                            |
| 输出位深与抖动        | 不适用                                                    |

### 4.4 CLI 与报告兼容

- 不新增必填 CLI 参数，不修改退出码和错误输出方式。
- `analyze.metrics` 加入 `rgb_channels`、`spatial_rgb_mean_grid_3x3`、噪声和锐度估计；旧字段原样保留。
- `grade` 加入可选的 `processing`、`output_encoding`、`warnings` 技术摘要；不把完整隐藏配方或 LUT 路径默认暴露。
- `compare` 继续保留现有 `checks`，并增加位深、输出编码和每通道差异摘要。
- `--show-parameters` 继续返回展开后的配方，并保留用户提供的相对 LUT 路径；内部解析路径不覆盖报告值。
- 所有新验证错误仍写 stderr 并返回 `2`；在写输出前完成 schema、LUT、ICC 和输出组合验证。

## 5. 分阶段实施计划

### 阶段 1：RGB 通道曲线与通道分析（已完成）

涉及文件：

- `scripts/photo_grade.py`
- `references/parameters.md`
- `SKILL.md`
- `tests/test_legacy_regression.py`
- `tests/test_curves_analysis.py`
- `tests/test_cli.py`
- `.github/workflows/publish-skill.yml`
- `.gitignore`
- `requirements-dev.txt`

实施：

- 先从当前提交建立算法级和 CLI 级特征测试，再修改功能。
- 增加 `channel_curves.red/green/blue`；执行顺序固定为旧主曲线之后。
- 通道曲线在编码 sRGB `[0,1]` 域中逐通道、分段线性插值；只处理非空曲线。
- 通道曲线激活时，输入通道先限制到定义域；输出由曲线端点保证在域内。
- 在局部 adjustment bundle 中允许 `channel_curves`，并在局部主曲线后执行。
- `analyze` 增加每通道均值、1/5/25/50/75/95/99 百分位、独立高低裁切比例、64-bin 归一化直方图和 3×3 空间 RGB 均值。
- 所有分析只统计 alpha 大于现有阈值的可见像素，保持与旧指标一致。
- 不生成 RGB Parade 图片。对 Agent 而言，机器可读直方图、百分位和空间 RGB 网格比额外视觉文件更稳定、低副作用且节省上下文；原图仍由 Agent 直接视觉检查。
- 修正文档中 HSL `+1.0–+1.5` 的实际旧路径限制说明，但不改变旧执行结果。
- CI 在发布前运行测试；测试与开发依赖不进入发布 ZIP。

测试：

- 旧配方的 `grade_pixels` 输出、8 位 PNG 解码像素、现有报告子树必须与基线完全一致。
- 验证主曲线先于通道曲线；只修改红曲线时绿色、蓝色通道不变。
- 空曲线和省略曲线均完全跳过，不产生隐含裁切。
- 验证端点、严格递增 x、NaN、布尔值、未知通道和非法点数。
- 直方图每通道总和为 1，透明像素不计入，百分位与 NumPy 参考结果一致。
- CLI 原命令帮助、成功退出码、错误退出码和旧 JSON 字段保持不变。

验收与停止条件：

- 旧回归全部通过，新增分析结果可由合成偏色、单通道裁切和空间渐变图自动证明正确。
- 中性新增字段不能改变旧输出。
- CI 未通过或旧像素发生任何变化时停止，不进入阶段 2。
- 建议独立提交：`增加 RGB 通道曲线与通道分析基线`。

#### 阶段 1 交接记录（2026-08-26）

- 实际接口：`schema_version: 1` 的 `parameters.channel_curves.red/green/blue` 均接受空数组或与主曲线相同的控制点；局部 `adjustments.channel_curves` 使用同一结构。`analyze.metrics`、`grade.before/after` 新增 `rgb_channels` 与 `spatial_rgb_mean_grid_3x3`，`grade.processing` 记录曲线技术摘要，`compare.rgb_channel_difference` 提供逐通道差异统计。
- 关键决定：保留旧主亮度曲线算法；主曲线后在编码 sRGB `[0,1]` 中按 R、G、B 独立执行分段线性插值。只有非空通道才在插值前限制输入定义域；省略或空曲线完全跳过。局部处理同样先主曲线、后通道曲线。
- 修改文件：`scripts/photo_grade.py`、`references/parameters.md`、`SKILL.md`、`tests/test_legacy_regression.py`、`tests/test_curves_analysis.py`、`tests/test_cli.py`、`.github/workflows/publish-skill.yml`、`.gitignore`、`requirements-dev.txt` 和本交接记录。
- 验证：修改前冻结 2 个旧特征基线；最终 `pytest` 30 项全部通过，覆盖算法、属性、回归和 CLI；`compileall`、`git diff --check` 通过；Skill `quick_validate.py` 在 Python UTF-8 模式下通过。实际运行 `analyze`、PNG/JPEG `grade` 和 `compare` 均成功。
- 兼容结果：旧 `grade_pixels` 浮点结果、8 位 PNG 解码像素和旧 JSON 报告子树与修改前基线完全一致；显式中性与省略通道曲线均与源输出逐像素一致；尺寸与 PNG alpha 保持不变；重复 PNG 渲染逐字节一致。
- 注意事项：仓库及历史没有代表性照片，视觉验收使用确定性的长渐变、单通道色块、阴影/高光和 alpha 合成图；未见新 clipping、色相断裂、banding、通道溢出或渐变断层。旧主亮度曲线对“纯黑像素 + 非零黑端点”的既有行为未更改，以避免破坏旧配方。Windows 默认 GBK 运行验证器会因其未指定编码而失败，使用计划要求的 UTF-8 模式可正常通过。

### 阶段 2：组合蒙版（已完成）

涉及文件：

- `scripts/photo_grade.py`
- `references/parameters.md`
- `tests/test_masks.py`
- `tests/test_cli.py`

实施：

- 将现有叶蒙版验证扩展为递归验证，但保留每种旧叶节点的 exact-key 规则和数值范围。
- 实现 `and=min`、`or=max`、`subtract=clip(A-B)`。
- 递归构建蒙版时复用同一阶段 RGB；每个局部调整项之间仍保持当前顺序执行。
- 每个节点最终输出必须有限且位于 `[0,1]`。
- 保留旧叶节点的“先 invert、后 opacity”行为。
- 不额外增加组合蒙版羽化参数；羽化属于叶节点，避免产生第二次难以预测的模糊。
- 在参数文档加入运算顺序、嵌套限制和典型表达；`SKILL.md` 不改，因为 Agent 已被要求完整读取参数参考。

测试：

- 旧 luminance/color/linear/radial 蒙版输出逐像素一致。
- 用解析数组验证 AND/OR 的交换性、幂等性、范围；验证 subtract 的方向性。
- 验证嵌套、节点反选、节点透明度、深度上限、叶节点上限和非法 arity。
- 验证多个颜色/亮度叶节点读取同一阶段快照。
- 在连续渐变、径向边缘和颜色范围边缘上验证输出连续，无 NaN、负数和超过 1 的值。
- CLI 测试非法树必须在创建输出文件前失败。

验收与停止条件：

- 所有旧叶蒙版回归一致。
- 复合蒙版的数值结果与独立参考公式一致。
- 合成羽化边界的覆盖值无单像素断裂；人工检查至少包含“亮部且位于径向区域”和“颜色范围减去高光”。
- 任一旧蒙版变化、递归限制可绕过或出现明显 seam 时停止。
- 建议独立提交：`增加可嵌套的组合蒙版`。

#### 阶段 2 交接记录（2026-08-26）

- 实现范围：`schema_version: 1` 的局部蒙版新增可递归 `composite` 节点，支持 `and=min`、`or=max` 和定向 `subtract=clip(A-B)`；根节点计为第 1 层，最多 6 层、每棵树最多 32 个叶节点，`and/or` 接受 2–8 个输入，`subtract` 严格接受 2 个输入。
- 关键决定：每个叶节点先执行自身 `invert`、再执行 `opacity`；复合节点在子节点完成后运算，再执行自身 `invert` 和 `opacity`。同一复合树的全部子节点读取同一阶段 RGB，多个局部调整项仍按旧顺序依次读取前一项结果。构建期再次执行深度和叶节点限制，避免绕过配方验证。
- 修改文件：`scripts/photo_grade.py`、`references/parameters.md`、`tests/test_masks.py`、`tests/test_cli.py` 和本交接记录；按计划未修改 `SKILL.md`、`agents/openai.yaml` 或后续阶段范围。
- 验证：修改前基线 `pytest` 30 项通过；最终 `pytest` 62 项全部通过，覆盖旧叶节点逐像素回归、参考公式、交换性/幂等性/方向性、嵌套、反选与透明度、同阶段快照、深度/叶节点/arity 限制、非法树预写入失败、alpha、确定性和连续羽化边界；`compileall`、`git diff --check` 和 UTF-8 模式 Skill `quick_validate.py` 通过。
- 兼容结果：旧 luminance/color/linear/radial 蒙版数值逐像素一致，旧配方、CLI、退出码和报告字段保持不变；复合节点为可选加法接口，省略时完全走旧路径。重复 PNG 输出逐字节一致，尺寸与 alpha 保持不变。
- 视觉验收：在 1536×772 的代表性水下照片上实际运行 analyze→grade→compare，并重开全尺寸、蒙版和 100% 主体局部；“亮部且位于径向区域”无几何 seam，“青色范围减去高光”正确保护明亮反光。RGB 64-bin 直方图各通道归一化为 1，输出有限；交集示例的高光裁切仅局部增加，减法示例保持源高光裁切比例，未见单像素断裂、banding、halo 或异常裁切。
- 遗留问题：本阶段无已知功能缺口；未提前实现阶段 3 及后续能力。

### 阶段 3：清晰度、纹理与保守去朦胧（已完成）

涉及文件：

- `scripts/photo_grade.py`
- `references/parameters.md`
- `SKILL.md`
- `tests/test_presence.py`
- `tests/test_local_adjustments.py`

实施：

- 新增 `presence.dehaze/clarity/texture`，范围统一为 `[-1,1]`。
- 使用确定性的浮点多尺度亮度分解，不再通过 8 位 Pillow 中间图：
  - 去朦胧：低频亮度范围恢复、黑位保护和克制的色度恢复。
  - 清晰度：中频、以中间调为主的局部对比。
  - 纹理：较小尺度的细节增益，抑制平坦区噪声。
- 按“去朦胧→清晰度→纹理”执行，均通过亮度或感知明度重建 RGB，避免直接三通道独立增强。
- 使用高光、阴影包络和梯度限制控制 halo；平坦区噪声门限来自局部残差估计。
- 允许局部 `clarity`、`texture`；局部结果先完整计算，再以浮点蒙版混合。
- 不允许局部 `dehaze`，避免低频估计跨蒙版边界失配。
- `SKILL.md` 只补充何时选择清晰度、纹理、去朦胧以及必须检查 halo、天空和皮肤噪声，不加入范围表。

测试：

- 常量图必须不变；中性值必须完全跳过。
- 正弦频率图证明 texture 对高频的响应高于 clarity，clarity 对中频高于 texture。
- 阶跃边缘测试控制过冲、欠冲和亮边/暗边宽度。
- 低对比雾化图验证 dehaze 增加低频分离但不中断灰阶单调性。
- 中性灰、肤色近似色和蓝色渐变测试色相漂移。
- 白噪声平坦区测试纹理/清晰度的噪声门限。
- 局部蒙版测试覆盖 0、1 和羽化区，确认无硬接缝。

验收与停止条件：

- 三个尺度在自动频率响应测试中可明确区分，证明没有引入重复滑块。
- 全强度合成阶跃边缘的额外过冲/欠冲不超过 `0.02`，且输出有限、在色域保护前保持可恢复。
- 人工检查天空、皮肤、树叶、建筑边缘和逆光雾景；任何明显 halo、塑料质感或蒙版边界都必须修正。
- 建议独立提交：`增加多尺度清晰度纹理与保守去朦胧`。

#### 阶段 3 交接记录（2026-08-26）

- 实现范围：`schema_version: 1` 新增可选 `parameters.presence.dehaze/clarity/texture`，均接受有限数值 `[-1,1]`、省略时展开为 `0`；全局固定按去朦胧→清晰度→纹理运行。局部 `local_corrections` 与 `local_adjustments` 新增 `clarity/texture`，继续拒绝局部 `dehaze`。
- 关键决定：使用 NumPy 浮点、边缘扩展的可分离多尺度亮度滤波，去朦胧、清晰度和纹理分别读取低、中、高频带；按图像尺寸确定并封顶滤波尺度。通过高光/阴影包络、强梯度保护、3×3 局部亮度包络与细节方向一致性门限抑制 halo 和平坦区噪声；按目标亮度重建 RGB，并以受色域约束的小幅色度恢复保持色相。局部版本先计算完整浮点变体，再按蒙版混合。
- 修改文件：`scripts/photo_grade.py`、`references/parameters.md`、`SKILL.md`、`tests/test_presence.py`、`tests/test_local_adjustments.py` 和本交接记录；`agents/openai.yaml` 的现有通用描述与调用策略未受影响，未修改。未改动阶段 4 及后续范围。
- 验证：修改前基线 `pytest` 62 项通过；最终 `pytest` 91 项全部通过，覆盖正常输入、正负边界、未知/非有限/布尔值、CLI 预写入失败、中性跳过、常量图、频率响应、阶跃边缘、雾化灰阶单调性、中性与色相、白噪声门限、随机极值、局部覆盖 0/1/羽化、alpha、确定性和旧像素回归。`compileall`、`git diff --check` 和 UTF-8 模式 Skill `quick_validate.py` 通过。
- 兼容结果：旧 `grade_pixels` 与 8 位 PNG 哈希回归保持逐像素一致；旧 schema、CLI、退出码和报告字段不变。省略或全零 presence 完全跳过；旧配方的 `processing` 结构不变，仅在 presence 实际激活时加法返回 `processing.presence` 技术摘要。重复 PNG 渲染逐字节一致，尺寸与 alpha 保持不变。
- 视觉验收：在 1536×772 的代表性水下照片上完成 analyze/grade/compare、全尺寸重开和全强度/局部羽化检查；全强度动态范围由 `0.21099` 增至 `0.24052`，阴影裁切保持 `0`，高光裁切仅在已有反光处由 `0.000097` 增至 `0.000381`，RGB 64-bin 直方图均归一化为 1。另用确定性天空/近似肤色/叶片纹理/建筑阶跃/雾化渐变诊断图检查，未见明显 halo、塑料质感、色相折断、结构化噪声或蒙版 seam；全强度合成阶跃额外过冲/欠冲不超过 `0.02`。
- 遗留问题：本阶段无已知功能缺口；高强度 presence 仍应按 `SKILL.md` 在天空、皮肤、细密纹理和高反差边缘进行全尺寸人工复核。未提前实现感知色彩、色域压缩、高位深输出或后续阶段能力。

### 阶段 4：感知色彩、色域保护与高位深输出（已完成）

涉及文件：

- `scripts/photo_grade.py`
- `scripts/png16.py`
- `references/parameters.md`
- `SKILL.md`
- `README.md`
- `requirements.txt`
- `tests/test_color_management.py`
- `tests/test_png16.py`
- `tests/test_metadata.py`
- `.github/workflows/publish-skill.yml`

实施：

- 实现固定 D65 sRGB↔XYZ↔OKLab/OKLCh 浮点转换，不增加可选工作空间。
- `rendering: perceptual` 时：
  - vibrance/saturation 在 OKLCh 色度上工作；
  - HSL 仍以当前色相分区确定选择权重，但在 OKLCh 中改变 hue/chroma/lightness；
  - 三向调色以 OKLab 对立色轴添加色度并保持明度。
- `oklch_compress` 使用固定软拐点和逐像素色度二分搜索，将颜色映射到 sRGB；保持 OKLCh 的 L 和 hue，近中性色不旋转。
- 所有新路径在关键边界检查 NaN/Inf；不得用静默 `nan_to_num` 隐藏算法错误。
- 旧 `legacy/clip` 路径保留现有硬裁剪和色彩算法。
- 新路径的 ICC 策略：
  - 成功转换后统一附加 sRGB ICC。
  - 无 ICC 时明确按 sRGB 处理，并在输出技术摘要中记录。
  - 有 ICC 但转换失败时，新路径在写文件前失败；旧路径保持像素行为并增加 warning。
  - CMYK JPEG 必须从原模式完成 ICC 转换后再进入 RGB，而不是先无管理地转换。
- 新增 `png_bit_depth: 16`。Pillow 不支持多通道 16 位内部图，因此使用 PyPNG/独立 `png16.py` 编码 RGB/RGBA16；PyPNG支持 RGB/RGBA 每通道 16 位，[其文档](https://drj11.gitlab.io/pypng/png.html)可作为实现依据。
- 16 位输出按 `round(clip(rgb)*65535)` 量化；8 位 alpha 扩展到 16 位时使用精确的 `value*257`，16 位源 alpha 保持原值。
- `png16.py` 写入并验证 IHDR 位深，保存当前适用的 ICC、EXIF、DPI 和 PNG 文本；遵循 [PNG 第三版规范](https://www.w3.org/TR/png-3/) 的 chunk 顺序。
- 对无 ICC 或明确 sRGB 的 16 位 PNG，可由 PyPNG 保留 16 位样本；任意非 sRGB ICC 的 16 位输入因 Pillow CMS 无法进行多通道 16 位转换，新路径明确拒绝并要求外部转换为 sRGB16。旧 8 位路径不变。
- `png_dither: tpdf` 使用固定坐标哈希产生零均值确定性 TPDF，仅在编码 sRGB 中、量化前作用于 RGB；不处理 alpha，不用于 JPEG 或 16 位 PNG。
- 报告加入源/输出位深、ICC 处理状态、色域映射模式、越界像素映射前后比例和运行库版本。
- `SKILL.md` 只说明何时选择 16 位 PNG、何时启用感知路径及 banding/gamut 验收；参数细节留在参考文档。

测试：

- OKLab 往返最大绝对误差不超过 `2e-5`。
- 中性轴保持无色度；感知饱和度不改变中性灰。
- 色域压缩对随机越界 RGB 输出有限且严格位于 `[0,1]`。
- 对非中性测试色，压缩前后 OKLCh 色相中位误差小于 `1°`；近中性色不参与色相误差统计。
- 旧配方继续通过全部像素回归。
- 16 位 RGB/RGBA 输出的 IHDR 位深为 16，独立解码样本与预期量化值一致。
- 尺寸、alpha、ICC、EXIF、DPI 和 PNG 文本按当前承诺保留。
- TPDF 对同一图像重复运行逐字节一致；大渐变上的平均量化偏差小于 `0.05 LSB`，且长平台长度低于无抖动版本。
- 非法 ICC、非法位深/格式组合在写输出前失败。

验收与停止条件：

- 新路径通过数值、编码器和元数据测试；旧路径无任何像素回归。
- 输出必须能被 Pillow和 PyPNG 两个独立读取路径重新打开。
- 人工检查高饱和花朵、霓虹、肤色、蓝天和长渐变，确认无可见色相折断、色域边缘断层或结构化抖动纹理。
- 任一元数据/alpha 丢失、16 位实际写成 8 位、ICC 状态不明确或旧结果变化时停止。
- 建议独立提交：`增加感知色彩色域保护与高位深 PNG`。

#### 阶段 4 交接记录（2026-08-26）

- 实现范围：`schema_version: 1` 新增可选 `parameters.color_management.rendering/gamut_mapping` 与 `parameters.output.png_bit_depth/png_dither`。感知路径以固定 D65 sRGB↔XYZ↔OKLab/OKLCh 变换处理全局及局部 vibrance/saturation、HSL 和三向调色；`oklch_compress` 在全局颜色阶段后和最终局部调整后执行。新增独立 `scripts/png16.py`，使用 PyPNG 读写 RGB16/RGBA16，并保留当前承诺的 ICC、EXIF、DPI 与 PNG 文本。
- 关键决定：默认 `legacy/clip + 8-bit + none` 完全跳过新颜色与量化路径。色域压缩使用固定 `C=0.10` 软拐点、`0.08` 肩部和 24 次逐像素色度二分搜索，并按 262,144 像素分块控制临时内存；该固定响应避免把 sRGB 非凸蓝色边缘显露成轮廓。LittleCMS 生成的 sRGB ICC 头部时间戳被规范化，保证跨 CLI 进程编码确定性。16 位非 sRGB/无效 ICC 输入按计划在写入前拒绝，CMYK 严格路径从原 CMYK 模式进入 ICC 变换。
- 修改文件：`scripts/photo_grade.py`、`scripts/png16.py`、`references/parameters.md`、`SKILL.md`、`README.md`、`requirements.txt`、`requirements-dev.txt`、`tests/test_color_management.py`、`tests/test_png16.py`、`tests/test_metadata.py`、`.github/workflows/publish-skill.yml` 和本交接记录。`agents/openai.yaml` 与图标不受接口和调用策略影响，按计划未修改。
- 验证：修改前基线 `pytest` 91 项通过；最终 `pytest` 117 项全部通过，覆盖 OKLab 往返、中性轴、感知色彩、HSL `+1.5`、蓝色色域 cusp 连续性、随机越界色、schema 边界/无效值、CLI 预写入失败、16 位 RGB/RGBA 样本、8→16 alpha 精确扩展、16 位源样本回归、ICC/EXIF/DPI/文本、CMYK 原模式、非法 ICC、TPDF 偏差/平台/确定性和旧像素回归。`compileall`、`pip check`、CLI smoke、`git diff --check` 及 UTF-8 模式 Skill `quick_validate.py` 通过。
- 兼容结果：旧 `grade_pixels` 浮点哈希、8 位 PNG 解码像素和旧报告子树保持逐像素一致；旧 schema、命令、参数、退出码和既有字段类型不变。新报告只加法增加位深、ICC、色域映射、库版本与可选 warning。Pillow 与 PyPNG 均可独立重开 16 位输出，IHDR、报告与独立解码均确认每通道 16 位；尺寸与 alpha 检查通过。
- 视觉验收：在 1536×772 水下实际照片上完成 analyze→grade→compare、全尺寸与 100% 主体/肤色/水体检查；以确定性的全色相高饱和场、蓝天长渐变、肤色渐变和霓虹带补足场景覆盖。初次视觉检查发现蓝色色域边缘楔形轮廓，修正软拐点后新增回归测试；最终诊断图最大相邻 RGB 距离为 `0.00726`，无可见色相折断、色域边缘断层、结构化抖动、banding 或异常肤色污染。最终色域外比例为 `0`，RGB 64-bin 直方图各通道和为 `1`；TPDF 重复输出逐字节一致，平均量化偏差和最长平台满足测试阈值。
- 遗留问题：本阶段无已知功能缺口。PyPNG 16 位编码与 OKLCh 二分搜索相对 8 位旧路径更慢，属于显式新功能的预期成本；任意非 sRGB ICC 的全精度 16 位输入仍需外部转换，未扩张到阶段 5 或后续范围。

### 阶段 5：RGB 原色校准与 3D LUT

涉及文件：

- `scripts/photo_grade.py`
- `scripts/cube_lut.py`
- `references/parameters.md`
- `SKILL.md`
- `README.md`
- `tests/test_rgb_primaries.py`
- `tests/test_cube_lut.py`
- `tests/fixtures/luts/`

实施：

- 将 `rgb_primaries`定位为“已渲染 sRGB 图片的创意原色校准”，不宣称替代 RAW 相机配置文件。
- 对线性 sRGB 的 R/G/B 基向量在 OKLCh 中调整 hue/saturation，构造 3×3 变换矩阵，并归一化使 `[1,1,1]` 映射为自身。
- 原色校准位于白平衡前，只允许全局使用；全部中性值时完全跳过。
- 原色 hue 建议验证范围 `[-30°,30°]`，saturation `[-1,1]`。
- `.cube` 只支持一个纯 3D LUT：
  - 支持注释、`TITLE`、`LUT_3D_SIZE`、`DOMAIN_MIN`、`DOMAIN_MAX`。
  - 拒绝 1D LUT、1D shaper+3D 混合、重复指令、未知非数据指令、NaN/Inf。
  - LUT 尺寸限制为 `2–65`，数据行必须精确等于 `size³`。
  - LUT 输出值限制为 `[0,1]`，因为当前 Skill 只支持显示参考 sRGB JPEG/PNG，不支持 Log/HDR 技术 LUT。
  - 相对路径以配方 JSON 所在目录解析；报告保留原始路径字符串。
- 按 Adobe `.cube` 数据顺序解析，固定使用 tetrahedral 插值；不暴露插值模式滑块。
- 输入通过 `DOMAIN_MIN/MAX` 归一化并在 LUT 域边界裁切；报告域外输入比例。
- LUT 在编码 sRGB 中执行；强度在 LUT 输入和输出之间做编码 RGB 线性混合，之后立即进行所选色域映射。
- LUT 文件在图像处理和输出创建前完整解析验证；失败沿用退出码 `2`。
- `SKILL.md` 只增加“用户提供 `.cube` 时可使用、仅支持显示参考 sRGB 3D LUT、必须验证”的触发与边界。
- 测试 LUT 只保留小型手写 identity、通道交换和已知映射文件；不加入商业 LUT。

测试：

- 中性原色校准完全跳过；非中性校准保持灰轴误差小于 `1e-6`。
- 单独调整一个原色时，基色和混合色变化方向符合参考矩阵，且无 NaN/Inf。
- 2³、3³ identity LUT 在所有网格顶点、边、面和随机内部点上保持输入。
- tetrahedral 插值与独立标量参考实现逐点比较。
- strength `0` 返回原图，`1` 返回完整 LUT，`0.5` 返回规定混合。
- 验证 DOMAIN、数据顺序、大小写扩展名、空文件、短数据、多余数据、非有限值、路径不存在和超限尺寸。
- LUT 失败时不得留下新输出。
- 与一套独立参考实现比较固定 LUT 输出，允许误差不超过 `1e-6`。

验收与停止条件：

- 原色校准保持中性轴，LUT 与参考实现一致。
- 人工检查原色校准对肤色、中性色和彩色高光的副作用；检查 LUT 强度混合是否平滑且无色阶断裂。
- 若必须增加 Log、ACES、1D shaper 或多个 LUT 才能让现有接口正确工作，则停止并另行设计，不在本阶段扩张范围。
- 建议独立提交：`增加 RGB 原色校准与三维 LUT`。

### 阶段 6：锐化增强与最终整体回归（已完成，本次范围收敛）

本次实施以 2026-08-27 用户指定范围为准：不实施阶段 5，不新增亮度/色度降噪，不新增噪声、锐度或边缘密度分析指标；新增 schema 字段仅限 `sharpen_threshold` 与 `sharpen_edge_protection`。项目无须兼容历史配方像素，因此实现优先保证结构清晰、职责明确和中性跳过；现有 `denoise`、`sharpen`、`sharpen_radius` 保留。

涉及文件：

- `scripts/photo_grade.py`
- `references/parameters.md`
- `SKILL.md`
- `README.md`
- `tests/test_detail.py`
- `tests/test_full_pipeline.py`
- `tests/visual_regression.py`
- `.github/workflows/publish-skill.yml`

实施：

- 原样保留 `detail.denoise` 的 RGB 3×3 中值路径，不新增降噪字段或算法。
- 旧 `sharpen` 和 `sharpen_radius` 继续控制当前 unsharp amount/radius。
- `sharpen_threshold` 对亮度 unsharp 残差执行平滑门限，只负责抑制低幅平坦区噪声。
- `sharpen_edge_protection` 使用按锐化半径扩张的局部亮度梯度，只负责抑制强边缘两侧增量。
- 两个新字段分别为零时跳过各自权重分支；`sharpen: 0` 时连模糊与权重计算都跳过。
- 锐化继续位于所有调色和局部调整之后；RGB 模糊使用 alpha 感知的预乘处理，alpha 样本本身不参与锐化。
- `SKILL.md` 只增加何时选择两个保护参数及平坦区、细纹理、强边缘、饱和/透明边缘的验收说明，不加入完整范围。
- `visual_regression.py` 从外部指定的、未提交的合法照片目录生成中性、结构、presence 和阶段 1–4 完整管线结果，同时保存配方、analyze/grade/compare 报告及 SHA-256；生成文件进入已忽略目录且不进入 Skill 发布包。

测试：

- 显式中性完整 schema 的 8 位 RGB 与 alpha 和源文件逐像素一致；新锐化字段为零时与省略字段结果一致。
- 现有中值降噪在平坦区脉冲噪声上保持有效，不扩展其职责。
- 锐化阈值必须抑制平坦区噪声；边缘保护必须减少阶跃边缘过冲且保留中等纹理。
- 验证高光、黑位、饱和边缘和透明边缘不会产生 NaN、彩边或 alpha 变化。
- 完整配方覆盖阶段 1–4 的通道曲线、嵌套蒙版、presence、感知色彩、色域压缩、现有降噪、新锐化和 16 位输出；明确不包含阶段 5 原色或 LUT。
- CLI 覆盖 analyze→grade→compare，确认旧字段、增量字段、退出码和 `--show-parameters`。

验收与停止条件：

- 平坦区门限测试显示锐化后噪声接近源噪声，同时细纹理仍保留冻结的增益比例。
- 新锐化在测试阶跃边缘上的过冲必须低于相同 amount/radius 的旧锐化。
- 全功能管线不得改变尺寸或 alpha；所有输出可重开，指标有限。
- 仓库内真实照片 smoke 与合成诊断图必须通过；更广的人像、夜景、高 ISO、蓝天、树叶/织物、逆光雾景和霓虹语料由外部视觉回归目录按需补充，不提交照片。
- 任何明显蜡质皮肤、天空色噪斑、锐化白边、mask seam 或 8 位 banding 均为停止条件。
- 建议独立提交：`增强锐化保护并完成整体回归`。

#### 阶段 6 交接记录（2026-08-27）

- 实现范围：`schema_version: 1` 的 `parameters.detail` 新增且仅新增 `sharpen_threshold`、`sharpen_edge_protection`，均接受有限数值 `[0,1]`、省略时展开为 `0`。保留 `denoise`、`sharpen`、`sharpen_radius`；未实施阶段 5，未增加亮度/色度降噪或任何分析指标。
- 关键决定：门限读取 RGB unsharp 增量的绝对亮度残差，以固定平滑过渡抑制低幅细节；边缘保护读取按 `ceil(sharpen_radius)` 扩张的 3×3 局部最大亮度梯度，以固定 `0.04–0.18` knee 衰减强边缘增量。两个权重统一作用于 RGB 增量，避免逐通道门限制造彩边。RGBA 模糊采用预乘 RGB/alpha 后反预乘，避免隐藏色污染可见透明边缘；alpha 从不进入锐化结果。
- 回归基础设施：新增 `tests/visual_regression.py`，递归读取外部 JPEG/PNG，分别从原图生成 A 中性、B 曲线/组合蒙版、C presence、D 阶段 1–4 完整管线四组 PNG；每组保存内部配方、grade/compare 报告、输出哈希，整批保存 analyze 与汇总报告。默认输出位于已忽略的 `tests/output/visual-regression/`，发布工作流继续排除整个 `tests/`。
- 测试覆盖：新增 `tests/test_detail.py` 与 `tests/test_full_pipeline.py`。门限后的平坦噪声标准差不超过源的 `1.08×` 且低于无门限锐化的 `0.6×`；全保护阶跃过冲低于无保护的 `0.2×`，中等细纹理增益至少保留 `0.75×`。另覆盖现有中值降噪、高光、黑位、饱和边缘、透明隐藏色、中性完整 schema、16 位 RGBA、有限 JSON、重开与 analyze→grade→compare。
- 验证：修改前 `pytest` 125 项通过；最终 `pytest` 140 项全部通过。`compileall`、`pip check`、`git diff --check`、产品 CLI 帮助/analyze、视觉回归 analyze→grade→compare smoke 及 UTF-8 模式 Skill `quick_validate.py` 通过。CI 增加源码编译和真实四阶段视觉回归 smoke，未增加依赖或产品 CLI 命令。
- 视觉验收：在仓库 1536×772 水下真实照片上生成四阶段结果并原尺寸查看，4/4 阶段通过尺寸/alpha/重开检查；中性、结构、presence、完整管线的动态范围依次为 `0.21099`、`0.23965`、`0.24094`、`0.25194`，完整管线高光/阴影裁切均为 `0`。未见可见锐化白边、色相折断、结构化噪声、mask seam 或 banding；合成图补足平坦噪声、细纹理、阶跃、高光、黑位、饱和与透明边缘。
- 修改文件：`scripts/photo_grade.py`、`references/parameters.md`、`SKILL.md`、`README.md`、`tests/test_detail.py`、`tests/test_full_pipeline.py`、`tests/visual_regression.py`、`.github/workflows/publish-skill.yml` 和本交接记录。`requirements*.txt`、`agents/openai.yaml`、图标与 `update.py` 均未修改。
- 遗留说明：外部照片目录由使用者提供，仓库不提交人像、夜景、高 ISO 等版权或隐私素材；运行器已为这些语料提供可重复的生成与报告路径。本阶段无已知功能缺口。

## 6. 最终跨阶段回归与视觉验证

### 自动化矩阵

输入类型：

- JPEG：无 ICC、sRGB ICC、非 sRGB ICC、CMYK、EXIF 方向和 DPI。
- PNG：RGB、RGBA、灰度、灰度 alpha、调色板透明、8 位、16 位 sRGB。
- 极端图：全黑、全白、单像素、全透明、低饱和、中性灰、高饱和、单通道裁切、长渐变。

配方类型：

- 当前文档示例配方。
- 所有旧字段的代表性组合。
- 每个新增段单独激活。
- 全功能组合。
- 缺省参数、显式中性参数和非法参数。

必须长期保持：

- 旧配方的 8 位 PNG 解码 RGB/alpha 与基线完全一致。
- JPEG 在固定依赖版本下解码像素一致；跨 Pillow/libjpeg 版本比较像素和指标，不比较压缩文件字节。
- 现有 JSON 字段和值不变；新增字段只能追加。
- 尺寸、alpha 存在性和 alpha 样本不变。
- 中性新增字段不改变旧结果。
- 输出不包含 NaN/Inf，编码位深与报告一致。
- 更新检查行为、`--skip-update-check` 和 `MESSAGE` 兼容。

### 人工视觉判断

自动测试只能发现数值越界、裁切、频率响应、边缘过冲、色相偏差和接缝候选，不能代替以下判断：

- 肤色是否自然且跨明暗稳定。
- 天空和墙面是否出现可见 banding 或抖动纹理。
- 清晰度、纹理、锐化是否形成 halo、脏边或塑料感。
- 去朦胧是否制造不自然黑边或过饱和。
- 组合蒙版是否暴露几何边界。
- 感知色域压缩是否保持审美上的色彩层次。
- LUT 和原色校准是否符合预期风格，而非仅数值合法。
- 大胆版本是否仍满足 `SKILL.md` 的灰度结构和场景光线要求。

每阶段审查必须同时查看单张全尺寸、100% 局部和所有风格并排结果；不得只依赖缩略图或指标。

## 7. 文档边界

需要修改 `SKILL.md` 的内容：

- 阶段 1：Agent 应读取并使用新的逐通道分析数据。
- 阶段 3：清晰度、纹理、去朦胧的选择条件及 halo/噪声检查。
- 阶段 4：感知路径、16 位 PNG 的使用条件和 banding/gamut 验收。
- 阶段 5：用户提供 `.cube` 时的触发、支持边界和失败原则。
- 阶段 6：根据亮度/色度噪声与边缘指标决定降噪和锐化。

只修改 Python、参数文档和测试，不修改 `SKILL.md` 的内容：

- 完整字段名、范围、默认值和 JSON 示例。
- 曲线插值、OKLab 公式、蒙版递归限制、LUT 数据顺序。
- PyPNG、ICC chunk、抖动和锐化阈值实现细节。
- 开发路线图、提交记录、测试实现和兼容矩阵。

`agents/openai.yaml` 和图标无需修改。`update.py` 无功能依赖变化，也无需修改。

## 8. 主要风险与已选推荐

- **旧结果稳定性**：禁止重写旧算法来“顺便改进”。推荐保留旧函数和分支，新行为由字段显式激活。
- **感知空间选择**：推荐固定 OKLab/OKLCh，适合当前 SDR sRGB 范围且可用 NumPy 确定性实现；不引入 ACES、JzAzBz 或可配置工作空间。
- **RGB Parade 形式**：推荐只输出机器可读的逐通道直方图、百分位和空间 RGB 网格；不在 analyze 默认创建图片。
- **16 位 PNG**：推荐增加 PyPNG 运行依赖并隔离在 `scripts/png16.py`；不尝试依赖 Pillow 的非公开 16 位 RGB 模式。
- **任意 ICC 的 16 位输入**：当前技术栈无法可靠完成多通道 16 位 ICC 转换。推荐只对明确 sRGB 的 16 位 PNG 保持源精度，其他配置在新路径明确失败，不静默降级。
- **抖动**：推荐固定、确定性的 TPDF，仅用于 8 位 PNG；不增加强度或种子滑块。
- **原色校准定位**：推荐作为显示参考 sRGB 的创意基色变换，而不是相机配置文件模拟。
- **LUT 范围**：推荐只支持一个显示参考 sRGB 3D `.cube`、固定 tetrahedral 插值；不支持 1D shaper、Log、HDR、ACES 或 LUT 堆栈。
- **性能**：多尺度滤波、组合蒙版和 tetrahedral LUT 必须采用分块或控制临时数组；中性旧配方运行时间不得出现显著回退。
- **跨环境确定性**：推荐在 JSON 报告记录 Python、NumPy、Pillow、PyPNG 版本，并在 CI 固定主验证版本；对 JPEG 只承诺同环境重复确定性，不承诺跨 libjpeg 文件字节一致。

当前没有必须由用户补充才能实施的阻塞决策；以上推荐应作为实现默认值。若未来要求任意 ICC 的全精度 16 位输入、Log/ACES LUT 或多个 LUT 堆叠，应单独立项，而不是扩张本计划的 v1 接口。
