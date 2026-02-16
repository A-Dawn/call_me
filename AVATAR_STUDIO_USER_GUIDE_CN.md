# Call Me 立绘处理用户使用指南（Avatar Studio）

本文面向使用 `plugins/call_me` 的前端用户与运维同学，覆盖当前已实现的立绘系统：

如果你只想快速部署，请先看白痴版：`plugins/call_me/AVATAR_STUDIO_USER_GUIDE_LITE_CN.md`

- 角色化立绘（`avatar_characters`）
- 整图 + 部件混合渲染（DOM 2D）
- 触区触摸反馈（本地视觉反馈）
- 与旧版 `avatar-map` 的兼容联动

适用页面：

- `http://127.0.0.1:8989/`（通话主页立绘展示）
- `http://127.0.0.1:8989/settings/avatar-studio`（立绘工作台）
- `http://127.0.0.1:8989/settings/avatar`（旧版快速入口）

## 1. 功能总览

当前版本支持：

1. 角色管理：新建角色、切换激活角色、删除非激活角色。
2. 素材管理：
   - 整图模式（`fullMap`）：按情绪绑定整张立绘。
   - 部件模式（`parts`）：上传眼睛、嘴型、眉毛、效果层等部件。
   - 可混合使用。
3. 微动作：
   - 呼吸（`idle_breath`）
   - 轻摆（`idle_sway`）
   - 口型强度（`speaking_lipsync.sensitivity`）
4. 触摸反馈：
   - 在立绘上配置触区（矩形）
   - 点击触区触发 `reaction_id` 对应的视觉时间线动画
5. 实时预览：
   - 预览情绪切换
   - 预览 speaking energy（口型强度）
   - 预览触区拖拽与缩放

## 2. 核心概念（先理解再操作）

### 2.1 角色（Character）

- 每个角色包含一份完整配置 `AvatarCharacterConfigV1`。
- 通话主页始终渲染“当前激活角色”。
- 删除限制：不能删除当前激活角色。

### 2.2 整图（fullMap）与部件（parts）

- `fullMap`：一张图对应一个情绪（`neutral/happy/sad/angry/shy/surprised`）。
- `parts`：按 `slot + emotion` 定义部件图层。

渲染基座规则：

1. 若存在 `body_base` 部件，则以 `body_base` 作为基座，不再显示 `fullMap` 基座图。
2. 若不存在 `body_base`，则使用 `fullMap` 作为基座图。

`fullMap` 缺省回退顺序（当前实现）：

1. 当前情绪
2. `neutral`
3. `happy`
4. `sad`
5. 若仍缺失，则显示空态占位

建议：至少配置 `neutral` 整图，保证任何场景都不会空白。

### 2.3 部件匹配优先级（非常关键）

同一 `slot` 匹配优先级：

1. `emotion == 当前情绪`
2. `emotion == neutral`
3. `emotion == all`

注意：

- 同一 `slot` 不建议保留多个可同时生效的部件，否则可能出现叠层（比如多个嘴型叠加）。
- 如果你要做“通用部件”，优先保留一份 `emotion=all`。

### 2.4 触区与反应（Hit Area / Reaction）

- 触区坐标是归一化坐标（`x/y/w/h` 均为 `0~1`）。
- 触发逻辑在前端本地完成，点击后立即反馈，不依赖服务端往返。
- 默认角色自带 4 个触区和 3 个反应：
  - 触区：`head` / `face_left` / `face_right` / `chest`
  - 反应：`pat_head` / `tap_face` / `tap_chest`

### 2.5 微动作参数

工作台当前可视化编辑三项：

1. 呼吸振幅 `idle_breath.amp_px`
2. 轻摆角度 `idle_sway.deg`
3. 口型灵敏度 `speaking_lipsync.sensitivity`

补充：

- 眨眼参数（`idle_blink`）已在配置中支持，但当前页面未提供滑条编辑。
- 若系统开启“减少动态效果”（OS `prefers-reduced-motion`），呼吸/轻摆/眨眼会自动降级或关闭。

## 3. 快速上手（5 分钟）

## 3.1 步骤一：进入立绘工作台

1. 打开主页 `/`。
2. 点击“设置”。
3. 进入“立绘工作台”（`/settings/avatar-studio`）。

## 3.2 步骤二：创建角色并设为激活

1. 在“角色管理”输入新角色名。
2. 点击“新建”。
3. 在下拉中选择该角色，点击“设为激活”。

说明：工作台新建角色默认会从当前激活角色复制一份初始配置（seed from legacy）。

## 3.3 步骤三：上传整图

1. 在“整图素材（fullMap）”选择情绪（建议先传 `neutral`）。
2. 选择图片文件，点击“上传整图”。
3. 对其它情绪重复上传（可选）。
4. 点击“保存发布”。

## 3.4 步骤四：预览与触摸

1. 在“实时预览”切换情绪、拖动 speaking energy。
2. 回到主页 `/`，点击立绘区域验证触摸反馈。

## 4. 三种推荐工作流

## 4.1 方案 A：纯整图（最快）

适合：先跑通、资源准备少。

操作：

1. 只上传 `fullMap`（至少 `neutral`）。
2. 不上传任何 `parts`。
3. 保存发布。

效果：

- 有情绪切换（按 fullMap）。
- 有呼吸/轻摆与触区反馈。
- 嘴型/眨眼细节不明显（建议后续补部件）。

## 4.2 方案 B：整图 + 脸部部件（推荐）

适合：沉浸感提升，成本可控。

建议最小部件集：

- `eyes_open`（emotion=all）
- `eyes_closed`（emotion=all）
- `mouth_closed`（emotion=all）
- `mouth_half`（emotion=all）
- `mouth_open`（emotion=all）

操作要点：

1. 保留 `fullMap` 作为基座（不要上传 `body_base`）。
2. 上传以上部件后，保存发布。
3. 在部件列表微调 `z/offset_x/offset_y` 对齐面部。

## 4.3 方案 C：全分层角色（高级）

适合：完全可控的立绘工程。

建议部件：

- `body_base`
- `eyes_open/eyes_closed`
- `mouth_closed/mouth_half/mouth_open`
- `brow_neutral/brow_happy/brow_sad/brow_angry`
- `fx_blush/fx_sweat`

操作要点：

1. 上传 `body_base` 后，fullMap 基座将不再显示。
2. 其余部件按 slot + emotion 细化。
3. 通过 `z` 管理遮挡顺序。

## 5. 工作台各区域操作说明

## 5.1 角色管理

- 新建：创建角色。
- 设为激活：切换当前通话页面使用的角色。
- 删除：仅可删除非激活角色。
- 刷新：重新加载角色与映射状态。

## 5.2 整图素材（fullMap）

- 每次上传只更新一个情绪对应的 `asset_id`。
- 上传后只是更新草稿，必须“保存发布”才写入后端。

## 5.3 部件素材（parts）

上传时可指定：

- `slot`（部件槽位）
- `emotion`（`all` 或具体情绪）

上传后新增一条部件记录，可在下方列表继续调整。

## 5.4 动作参数

- 呼吸振幅：太大容易“漂浮感”过强，建议 2~6 px。
- 轻摆角度：建议 0.6~1.8 deg。
- 口型灵敏度：建议 0.8~1.4，根据 TTS 音量波动调整。

## 5.5 触区编辑

- 点击触区主体：移动。
- 拖右下角小方块：缩放。
- 新增触区：默认 `reaction_id=pat_head`。
- 可编辑 `label` 和 `reaction_id`。

提示：当前工作台不提供 reaction timeline 图形化编辑，如需自定义 timeline，请用 API 提交完整 config。

## 5.6 部件列表

可直接编辑：

- `slot`
- `emotion`
- `z`
- `offset_x`
- `offset_y`

并支持单条删除。

## 6. 保存、生效与兼容

## 6.1 保存发布机制

- 上传整图/部件、拖拽触区、改动作参数都只作用于“草稿态”。
- 必须点击“保存发布”才会调用后端 `PUT /api/avatar-characters/{id}/config`。

## 6.2 激活机制

- 只有激活角色会在主页 `/` 立刻生效。
- 切换激活会同步更新旧版 `avatar-map` 映射，保证历史接口兼容。

## 6.3 旧版入口兼容

旧页面 `/settings/avatar` 仍可使用：

- 上传/删除情绪整图
- 其行为会反映到当前激活角色的 `fullMap`

适合快速改某个情绪整图，不适合做复杂分层编辑。

## 7. 资源规范建议

推荐格式：

- `PNG` 或 `WebP`（透明背景）
- 统一竖版比例，建议按 `1080x1440` 逻辑画布制作

建议规范：

1. 同角色全部部件使用同一原始画布尺寸导出。
2. 嘴型三档建议保持同锚点。
3. 眉毛/特效图层尺寸尽量只包住有效区域，减少误差。
4. 命名上带语义：`eyes_open_all.png`、`mouth_open_all.png`。

## 8. 常见问题与排查

### 8.1 上传成功但主页没变化

按顺序检查：

1. 是否点击了“保存发布”。
2. 该角色是否“设为激活”。
3. 浏览器是否仍在旧会话，尝试刷新页面。
4. `/api/assets/{asset_id}/file` 是否可访问。

### 8.2 立绘空白

常见原因：

1. `fullMap` 当前情绪和回退情绪都未配置。
2. 配了 `body_base` 但对应资产失效。
3. 资产被删除，引用已被清理。

建议：

- 至少保证 `fullMap.neutral` 有效。

### 8.3 口型不动 / 眨眼不明显

可能原因：

1. 未上传对应部件（`mouth_*` / `eyes_*`）。
2. `speaking_lipsync.sensitivity` 太低。
3. 系统启用了“减少动态效果”。

### 8.4 删除素材后部件丢失

这是预期行为：

- 删除 `asset` 时，后端会自动清理所有引用该 `asset_id` 的 `fullMap` 与 `parts`，防止悬挂引用。

### 8.5 触区点了没反应

检查：

1. `hitArea.enabled` 是否为 `true`
2. `reaction_id` 是否存在于 `reactions`
3. 是否在冷却时间（`cooldown_ms`）内重复触发

## 9. 面向脚本/高级用户的 API 速览

角色：

- `GET /api/avatar-characters/`
- `POST /api/avatar-characters/`
- `GET /api/avatar-characters/{character_id}`
- `PUT /api/avatar-characters/{character_id}/config`
- `DELETE /api/avatar-characters/{character_id}`
- `GET /api/avatar-characters/active`
- `PUT /api/avatar-characters/active`

兼容映射：

- `GET /api/avatar-map/active`
- `PUT /api/avatar-map/active`
- `PUT /api/avatar-map/bind`
- `DELETE /api/avatar-map/bind/{emotion}`

素材：

- `POST /api/assets/upload`
- `GET /api/assets/`
- `GET /api/assets/{asset_id}/file`
- `DELETE /api/assets/{asset_id}`

## 10. 最佳实践（建议直接照做）

1. 第一版先走“方案 B：整图 + 脸部部件”。
2. 永远先配好 `neutral` 整图。
3. 同一个 slot 尽量只保留一个有效部件（每种 emotion 一条）。
4. 每次编辑后先在工作台预览，再保存发布。
5. 保存后回主页做一次真实语音回合，验证 speaking 与触摸反馈。
