# Python Photo Color Grade

一个面向 Agent 的**非生成式**图片调色 Skill。它分析 JPEG 或 PNG 的画面与指标，自动设计场景自适应方向，并通过确定性的 Python 脚本直接输出成片。

[下载SKILL.zip](https://github.com/EShuoTan-Labs/skill-python-photo-color-grade/releases/latest/download/skill-python-photo-color-grade.zip)

## 特点

- 首轮根据实际画面，直接输出 3–6 个差异鲜明的强度 3 成片。
- 成片方向可覆盖自然修正、商业清透、胶片叙事、电影感和场景化大片。
- 使用字母选择风格，使用数字选择强度：`1 = 轻度`、`2 = 中等`、`3 = 明显`。
- 只回复字母时默认按强度 `3` 处理；支持多选，例如 `AC2` 会输出 A、C 两个中等强度版本。
- 强度 3 会真正体现所选风格，可使用更明确的曲线、色彩分离与局部塑光，同时自动检查溢出、光晕和肤色异常。

## 使用方式

上传照片并调用：

```text
@python-photo-color-grade 调色
```

技能会分析照片并直接返回类似下面的成片：

```text
A3 自然还原
B3 明亮商业
C3 低饱和叙事
D3 大片冲击
```

之后可回复 `D2`、`AC2` 或“B 再通透一点”等指令，只重新输出所选版本。精确参数默认不展示，明确要求时才返回最终成片实际使用的配方。

## 调色流程

处理顺序遵循类似 Lightroom 的工作流：

1. 解码、色彩管理与可选前置降噪
2. 白平衡
3. 曝光
4. 高光与阴影
5. 白色、黑色与对比度
6. 点曲线
7. 校正型局部蒙版
8. 去朦胧、清晰度与纹理
9. 自然饱和度、整体饱和度、HSL 与三向色彩分级（兼容或感知路径）
10. 色域保护
11. 创意型局部蒙版与最终色域保护
12. 输出锐化
13. 可选确定性抖动、8/16 位编码与元数据处理

## 非生成式

该技能不会生成、重绘或修补画面内容，也不会使用 AI 主体/天空分割。脚本不提供空间变换，并在编码后自动验证尺寸与 PNG 透明通道。

支持格式：JPEG、PNG。

不支持：HEIC、RAW、物体移除、磨皮液化、内容感知修补、生成式扩图或景深重绘。

## 本地脚本

依赖 Python 3、NumPy、Pillow 与 PyPNG：

```bash
python3 -m pip install -r requirements.txt
```

分析照片：

```bash
python3 scripts/photo_grade.py analyze input.jpg --pretty
```

执行调色：

```bash
python3 scripts/photo_grade.py grade input.jpg output_graded.jpg \
  --recipe recipe.json
```

比较原图与成片：

```bash
python3 scripts/photo_grade.py compare input.jpg output_graded.jpg --pretty
```

完整参数说明见 [`references/parameters.md`](references/parameters.md)。
