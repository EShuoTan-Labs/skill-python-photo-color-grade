# Python Photo Color Grade

一个面向 Agent 的**非生成式**图片调色skill。它先分析 JPEG 或 PNG 的亮度、动态范围、偏色和饱和度等指标，再让使用者选择审美方向与强度，随后通过确定性的 Python 脚本完成图像调色。

## 特点

- 首轮根据实际画面，提供 3–6 个差异鲜明的审美方向。
- 选项覆盖自然修正、商业清透、胶片叙事、电影感和场景化大片等方向。
- 使用字母选择风格，使用数字选择强度：`1 = 轻度`、`2 = 中等`、`3 = 明显`。
- 只回复字母时默认按强度 `3` 处理；支持多选，例如 `AC2` 会输出 A、C 两个中等强度版本。
- 强度 3 会真正体现所选风格，可使用更明确的曲线、色彩分离与局部塑光，同时自动检查溢出、光晕和肤色异常。

## 使用方式

上传照片并调用：

```text
@python-photo-color-grade 调色
```

技能会先分析照片并返回类似下面的选项：

```text
A. 自然还原｜中性、克制、真实层次
B. 明亮商业｜亮净、鲜活、清晰主体
C. 低饱和叙事｜收色、柔和曲线、故事感
D. 大片冲击｜大胆曲线、明确主色、局部塑光

强度：1 轻度 / 2 中等 / 3 明显
```

回复 `D3` 后会直接处理照片、验证结果并返回成片及实际参数，不会再次要求确认数值。

首轮会直接输出A3 B3 C3 D3四张图片，无需指定

## 调色流程

处理顺序遵循类似 Lightroom 的工作流：

1. 解码、色彩管理与可选前置降噪
2. 白平衡
3. 曝光
4. 高光与阴影
5. 白色、黑色与对比度
6. 点曲线
7. 校正型局部蒙版
8. 自然饱和度与整体饱和度
9. HSL 精调
10. 三向色彩分级
11. 创意型局部蒙版
12. 输出锐化
13. 编码与元数据处理

## 非生成式

该技能不会生成、重绘或修补画面内容，也不会使用 AI 主体/天空分割。它会保留人物、物体、文字、纹理、边缘、构图、几何结构、尺寸和透明通道。

支持格式：JPEG、PNG。

不支持：HEIC、RAW、物体移除、磨皮液化、内容感知修补、生成式扩图或景深重绘。

## 本地脚本

依赖 Python 3、NumPy 与 Pillow：

```bash
python3 -m pip install numpy pillow
```

分析照片：

```bash
python3 scripts/photo_grade.py analyze input.jpg --pretty
```

执行调色：

```bash
python3 scripts/photo_grade.py grade input.jpg output_graded.jpg \
  --exposure 0.20 --highlights -0.15 --shadows 0.18 \
  --vibrance 0.08 --sharpen 0.20 --sharpen-radius 0.8
```

比较原图与成片：

```bash
python3 scripts/photo_grade.py compare input.jpg output_graded.jpg --pretty
```

完整参数说明见 [`references/parameters.md`](references/parameters.md)。

