import { createRootRoute, createRoute } from '@tanstack/react-router'
import { RootLayout } from './root'
import { IndexPage } from './routes.index'
import { AssetsPage } from './routes.assets'
import { PresetsPage } from './routes.presets'
import { SettingsConnectionPage } from './routes.settings.connection'
import { SettingsAvatarPage } from './routes.settings.avatar'
import { SettingsAvatarStudioPage } from './routes.settings.avatar-studio'
import { SettingsDiagnosticsPage } from './routes.settings.diagnostics'

const rootRoute = createRootRoute({
  component: RootLayout,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: IndexPage,
})

const assetsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/assets',
  component: AssetsPage,
})

const presetsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/presets',
  component: PresetsPage,
})

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsConnectionPage,
})

const settingsConnectionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings/connection',
  component: SettingsConnectionPage,
})

const settingsAvatarRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings/avatar',
  component: SettingsAvatarPage,
})

const settingsAvatarStudioRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings/avatar-studio',
  component: SettingsAvatarStudioPage,
})

const settingsDiagnosticsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings/diagnostics',
  component: SettingsDiagnosticsPage,
})

export const routeTree = rootRoute.addChildren([
  indexRoute,
  assetsRoute,
  presetsRoute,
  settingsRoute,
  settingsConnectionRoute,
  settingsAvatarRoute,
  settingsAvatarStudioRoute,
  settingsDiagnosticsRoute,
])
