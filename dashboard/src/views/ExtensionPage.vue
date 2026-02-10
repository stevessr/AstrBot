<script setup>
import AstrBotConfig from "@/components/shared/AstrBotConfig.vue";
import ConsoleDisplayer from "@/components/shared/ConsoleDisplayer.vue";
import ReadmeDialog from "@/components/shared/ReadmeDialog.vue";
import ProxySelector from "@/components/shared/ProxySelector.vue";
import UninstallConfirmDialog from "@/components/shared/UninstallConfirmDialog.vue";
import McpServersSection from "@/components/extension/McpServersSection.vue";
import SkillsSection from "@/components/extension/SkillsSection.vue";
import ComponentPanel from "@/components/extension/componentPanel/index.vue";
import InstalledPluginsTab from "./extension/InstalledPluginsTab.vue";
import MarketPluginsTab from "./extension/MarketPluginsTab.vue";
import { useExtensionPage } from "./extension/useExtensionPage";

const pageState = useExtensionPage();

const {
  commonStore,
  t,
  tm,
  router,
  route,
  getSelectedGitHubProxy,
  conflictDialog,
  checkAndPromptConflicts,
  handleConflictConfirm,
  fileInput,
  activeTab,
  validTabs,
  isValidTab,
  getLocationHash,
  extractTabFromHash,
  syncTabFromHash,
  extension_data,
  getInitialShowReserved,
  showReserved,
  snack_message,
  snack_show,
  snack_success,
  configDialog,
  extension_config,
  pluginMarketData,
  loadingDialog,
  showPluginInfoDialog,
  selectedPlugin,
  curr_namespace,
  updatingAll,
  readmeDialog,
  forceUpdateDialog,
  updateAllConfirmDialog,
  changelogDialog,
  getInitialListViewMode,
  isListView,
  pluginSearch,
  loading_,
  currentPage,
  dangerConfirmDialog,
  selectedDangerPlugin,
  selectedMarketInstallPlugin,
  installCompat,
  versionCompatibilityDialog,
  showUninstallDialog,
  uninstallTarget,
  showSourceDialog,
  showSourceManagerDialog,
  sourceName,
  sourceUrl,
  customSources,
  selectedSource,
  showRemoveSourceDialog,
  sourceToRemove,
  editingSource,
  originalSourceUrl,
  extension_url,
  dialog,
  upload_file,
  uploadTab,
  showPluginFullName,
  marketSearch,
  debouncedMarketSearch,
  refreshingMarket,
  sortBy,
  sortOrder,
  randomPluginNames,
  normalizeStr,
  toPinyinText,
  toInitials,
  marketCustomFilter,
  plugin_handler_info_headers,
  pluginHeaders,
  filteredExtensions,
  filteredPlugins,
  filteredMarketPlugins,
  sortedPlugins,
  RANDOM_PLUGINS_COUNT,
  randomPlugins,
  shufflePlugins,
  refreshRandomPlugins,
  displayItemsPerPage,
  totalPages,
  paginatedPlugins,
  updatableExtensions,
  toggleShowReserved,
  toast,
  resetLoadingDialog,
  onLoadingDialogResult,
  failedPluginsDict,
  getExtensions,
  handleReloadAllFailed,
  checkUpdate,
  uninstallExtension,
  handleUninstallConfirm,
  updateExtension,
  showUpdateAllConfirm,
  confirmUpdateAll,
  cancelUpdateAll,
  confirmForceUpdate,
  updateAllExtensions,
  pluginOn,
  pluginOff,
  openExtensionConfig,
  updateConfig,
  showPluginInfo,
  reloadPlugin,
  viewReadme,
  viewChangelog,
  handleInstallPlugin,
  confirmDangerInstall,
  cancelDangerInstall,
  loadCustomSources,
  saveCustomSources,
  addCustomSource,
  openSourceManagerDialog,
  selectPluginSource,
  sourceSelectItems,
  editCustomSource,
  removeCustomSource,
  confirmRemoveSource,
  saveCustomSource,
  trimExtensionName,
  checkAlreadyInstalled,
  showVersionCompatibilityWarning,
  continueInstallIgnoringVersionWarning,
  cancelInstallOnVersionWarning,
  newExtension,
  normalizePlatformList,
  getPlatformDisplayList,
  resolveSelectedInstallPlugin,
  selectedInstallPlugin,
  checkInstallCompatibility,
  refreshPluginMarket,
  handleLocaleChange,
  searchDebounceTimer,
} = pageState;
import axios from "axios";
import { pinyin } from "pinyin-pro";
import { useCommonStore } from "@/stores/common";
import { useI18n, useModuleI18n } from "@/i18n/composables";
import defaultPluginIcon from "@/assets/images/plugin_icon.png";
import { getPlatformDisplayName } from "@/utils/platformUtils";

import { ref, computed, onMounted, onUnmounted, reactive, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

const commonStore = useCommonStore();
const { t } = useI18n();
const { tm } = useModuleI18n("features/extension");
const router = useRouter();
const route = useRoute();

const getSelectedGitHubProxy = () => {
  if (typeof window === "undefined" || !window.localStorage) return "";
  return localStorage.getItem("githubProxyRadioValue") === "1"
    ? localStorage.getItem("selectedGitHubProxy") || ""
    : "";
};

// 检查指令冲突并提示
const conflictDialog = reactive({
  show: false,
  count: 0,
});
const checkAndPromptConflicts = async () => {
  try {
    const res = await axios.get("/api/commands");
    if (res.data.status === "ok") {
      const conflicts = res.data.data.summary?.conflicts || 0;
      if (conflicts > 0) {
        conflictDialog.count = conflicts;
        conflictDialog.show = true;
      }
    }
  } catch (err) {
    console.debug("Failed to check command conflicts:", err);
  }
};
const handleConflictConfirm = () => {
  activeTab.value = "commands";
};

const fileInput = ref(null);
const activeTab = ref("installed");
const validTabs = ["installed", "market", "mcp", "skills", "components"];
const isValidTab = (tab) => validTabs.includes(tab);
const getLocationHash = () =>
  typeof window !== "undefined" ? window.location.hash : "";
const extractTabFromHash = (hash) => {
  const lastHashIndex = (hash || "").lastIndexOf("#");
  if (lastHashIndex === -1) return "";
  return hash.slice(lastHashIndex + 1);
};
const syncTabFromHash = (hash) => {
  const tab = extractTabFromHash(hash);
  if (isValidTab(tab)) {
    activeTab.value = tab;
    return true;
  }
  return false;
};
const extension_data = reactive({
  data: [],
  message: "",
});

// 从 localStorage 恢复显示系统插件的状态，默认为 false（隐藏）
const getInitialShowReserved = () => {
  if (typeof window !== "undefined" && window.localStorage) {
    const saved = localStorage.getItem("showReservedPlugins");
    return saved === "true";
  }
  return false;
};
const showReserved = ref(getInitialShowReserved());
const snack_message = ref("");
const snack_show = ref(false);
const snack_success = ref("success");
const configDialog = ref(false);
const extension_config = reactive({
  metadata: {},
  config: {},
});
const pluginMarketData = ref([]);
const loadingDialog = reactive({
  show: false,
  title: "",
  statusCode: 0, // 0: loading, 1: success, 2: error,
  result: "",
});
const showPluginInfoDialog = ref(false);
const selectedPlugin = ref({});
const curr_namespace = ref("");
const updatingAll = ref(false);

const readmeDialog = reactive({
  show: false,
  pluginName: "",
  repoUrl: null,
});

// 强制更新确认对话框
const forceUpdateDialog = reactive({
  show: false,
  extensionName: "",
});

// 更新全部插件确认对话框
const updateAllConfirmDialog = reactive({
  show: false,
});

// 插件更新日志对话框（复用 ReadmeDialog）
const changelogDialog = reactive({
  show: false,
  pluginName: "",
  repoUrl: null,
});

// 新增变量支持列表视图
// 从 localStorage 恢复显示模式，默认为 false（卡片视图）
const getInitialListViewMode = () => {
  if (typeof window !== "undefined" && window.localStorage) {
    return localStorage.getItem("pluginListViewMode") === "true";
  }
  return false;
};
const isListView = ref(getInitialListViewMode());
const pluginSearch = ref("");
const loading_ = ref(false);

// 分页相关
const currentPage = ref(1);

// 危险插件确认对话框
const dangerConfirmDialog = ref(false);
const selectedDangerPlugin = ref(null);
const selectedMarketInstallPlugin = ref(null);
const installCompat = reactive({
  checked: false,
  compatible: true,
  message: "",
});

// AstrBot 版本范围不兼容警告对话框
const versionCompatibilityDialog = reactive({
  show: false,
  message: "",
});

// 卸载插件确认对话框（列表模式用）
const showUninstallDialog = ref(false);
const pluginToUninstall = ref(null);

// 自定义插件源相关
const showSourceDialog = ref(false);
const sourceName = ref("");
const sourceUrl = ref("");
const customSources = ref([]);
const selectedSource = ref(null);
const showRemoveSourceDialog = ref(false);
const sourceToRemove = ref(null);
const editingSource = ref(false);
const originalSourceUrl = ref("");

// 插件市场相关
const extension_url = ref("");
const dialog = ref(false);
const upload_file = ref(null);
const uploadTab = ref("file");
const showPluginFullName = ref(false);
const marketSearch = ref("");
const debouncedMarketSearch = ref("");
const refreshingMarket = ref(false);
const sortBy = ref("default"); // default, stars, author, updated
const sortOrder = ref("desc"); // desc (降序) or asc (升序)
const randomPluginNames = ref([]);

// 插件市场拼音搜索
const normalizeStr = (s) => (s ?? "").toString().toLowerCase().trim();
const toPinyinText = (s) =>
  pinyin(s ?? "", { toneType: "none" })
    .toLowerCase()
    .replace(/\s+/g, "");
const toInitials = (s) =>
  pinyin(s ?? "", { pattern: "first", toneType: "none" })
    .toLowerCase()
    .replace(/\s+/g, "");
const marketCustomFilter = (value, query, item) => {
  const q = normalizeStr(query);
  if (!q) return true;

  const candidates = new Set();
  if (value != null) candidates.add(String(value));
  if (item?.name) candidates.add(String(item.name));
  if (item?.trimmedName) candidates.add(String(item.trimmedName));
  if (item?.display_name) candidates.add(String(item.display_name));
  if (item?.desc) candidates.add(String(item.desc));
  if (item?.author) candidates.add(String(item.author));

  for (const v of candidates) {
    const nv = normalizeStr(v);
    if (nv.includes(q)) return true;
    const pv = toPinyinText(v);
    if (pv.includes(q)) return true;
    const iv = toInitials(v);
    if (iv.includes(q)) return true;
  }
  return false;
};

const plugin_handler_info_headers = computed(() => [
  { title: tm("table.headers.eventType"), key: "event_type_h" },
  { title: tm("table.headers.description"), key: "desc", maxWidth: "250px" },
  { title: tm("table.headers.specificType"), key: "type" },
  { title: tm("table.headers.trigger"), key: "cmd" },
]);

// 插件表格的表头定义
const pluginHeaders = computed(() => [
  { title: tm("table.headers.name"), key: "name", width: "200px" },
  { title: tm("table.headers.description"), key: "desc", maxWidth: "250px" },
  { title: tm("table.headers.version"), key: "version", width: "100px" },
  { title: tm("table.headers.author"), key: "author", width: "100px" },
  { title: tm("table.headers.status"), key: "activated", width: "100px" },
  {
    title: tm("table.headers.actions"),
    key: "actions",
    sortable: false,
    width: "220px",
  },
]);

// 过滤要显示的插件
const filteredExtensions = computed(() => {
  const data = Array.isArray(extension_data?.data) ? extension_data.data : [];
  if (!showReserved.value) {
    return data.filter((ext) => !ext.reserved);
  }
  return data;
});

// 通过搜索过滤插件
const filteredPlugins = computed(() => {
  if (!pluginSearch.value) {
    return filteredExtensions.value;
  }

  const search = pluginSearch.value.toLowerCase();
  return filteredExtensions.value.filter((plugin) => {
    const supportPlatforms = Array.isArray(plugin.support_platforms)
      ? plugin.support_platforms.join(" ").toLowerCase()
      : "";
    const astrbotVersion = (plugin.astrbot_version ?? "").toLowerCase();
    return (
      plugin.name?.toLowerCase().includes(search) ||
      plugin.desc?.toLowerCase().includes(search) ||
      plugin.author?.toLowerCase().includes(search) ||
      supportPlatforms.includes(search) ||
      astrbotVersion.includes(search)
    );
  });
});

// 过滤后的插件市场数据（带搜索）
const filteredMarketPlugins = computed(() => {
  const data = Array.isArray(pluginMarketData.value) ? pluginMarketData.value : [];
  if (!debouncedMarketSearch.value) {
    return data;
  }

  const search = debouncedMarketSearch.value.toLowerCase();
  return data.filter((plugin) => {
    // 使用自定义过滤器
    return (
      marketCustomFilter(plugin.name, search, plugin) ||
      marketCustomFilter(plugin.desc, search, plugin) ||
      marketCustomFilter(plugin.author, search, plugin)
    );
  });
});

// 所有插件列表，推荐插件排在前面
const sortedPlugins = computed(() => {
  let plugins = [...filteredMarketPlugins.value];

  // 根据排序选项排序
  if (sortBy.value === "stars") {
    // 按 star 数排序
    plugins.sort((a, b) => {
      const starsA = a.stars ?? 0;
      const starsB = b.stars ?? 0;
      return sortOrder.value === "desc" ? starsB - starsA : starsA - starsB;
    });
  } else if (sortBy.value === "author") {
    // 按作者名字典序排序
    plugins.sort((a, b) => {
      const authorA = (a.author ?? "").toLowerCase();
      const authorB = (b.author ?? "").toLowerCase();
      const result = authorA.localeCompare(authorB);
      return sortOrder.value === "desc" ? -result : result;
    });
  } else if (sortBy.value === "updated") {
    // 按更新时间排序
    plugins.sort((a, b) => {
      const dateA = a.updated_at ? new Date(a.updated_at).getTime() : 0;
      const dateB = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      return sortOrder.value === "desc" ? dateB - dateA : dateA - dateB;
    });
  } else {
    // default: 推荐插件排在前面
    const pinned = plugins.filter((plugin) => plugin?.pinned);
    const notPinned = plugins.filter((plugin) => !plugin?.pinned);
    return [...pinned, ...notPinned];
  }

  return plugins;
});

const RANDOM_PLUGINS_COUNT = 6;

const randomPlugins = computed(() => {
  const allPlugins = pluginMarketData.value;
  if (allPlugins.length === 0) return [];

  const pluginsByName = new Map(allPlugins.map((plugin) => [plugin.name, plugin]));
  const selected = randomPluginNames.value
    .map((name) => pluginsByName.get(name))
    .filter(Boolean);

  if (selected.length > 0) {
    return selected;
  }

  return allPlugins.slice(0, Math.min(RANDOM_PLUGINS_COUNT, allPlugins.length));
});

const shufflePlugins = (plugins) => {
  const shuffled = [...plugins];
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
};

const refreshRandomPlugins = () => {
  const shuffled = shufflePlugins(pluginMarketData.value);
  randomPluginNames.value = shuffled
    .slice(0, Math.min(RANDOM_PLUGINS_COUNT, shuffled.length))
    .map((plugin) => plugin.name);
};

// 分页计算属性
const displayItemsPerPage = 9; // 固定每页显示 9 个卡片（3 行）

const totalPages = computed(() => {
  return Math.ceil(sortedPlugins.value.length / displayItemsPerPage);
});

const paginatedPlugins = computed(() => {
  const start = (currentPage.value - 1) * displayItemsPerPage;
  const end = start + displayItemsPerPage;
  return sortedPlugins.value.slice(start, end);
});

const updatableExtensions = computed(() => {
  const data = Array.isArray(extension_data?.data) ? extension_data.data : [];
  return data.filter((ext) => ext.has_update);
});

// 方法
const toggleShowReserved = () => {
  showReserved.value = !showReserved.value;
  // 保存到 localStorage
  if (typeof window !== "undefined" && window.localStorage) {
    localStorage.setItem("showReservedPlugins", showReserved.value.toString());
  }
};

const toast = (message, success) => {
  snack_message.value = message;
  snack_show.value = true;
  snack_success.value = success;
};

const resetLoadingDialog = () => {
  loadingDialog.show = false;
  loadingDialog.title = tm("dialogs.loading.title");
  loadingDialog.statusCode = 0;
  loadingDialog.result = "";
};

const onLoadingDialogResult = (statusCode, result, timeToClose = 2000) => {
  loadingDialog.statusCode = statusCode;
  loadingDialog.result = result;
  if (timeToClose === -1) return;
  setTimeout(resetLoadingDialog, timeToClose);
};

const failedPluginsDict = ref({});

const getExtensions = async () => {
  loading_.value = true;
  try {
    const res = await axios.get("/api/plugin/get");   
    Object.assign(extension_data, res.data);
    
    const failRes = await axios.get("/api/plugin/source/get-failed-plugins");    
    failedPluginsDict.value = failRes.data.data || {};
    
    checkUpdate();
  } catch (err) {
    toast(err, "error");
  } finally {
    loading_.value = false;
  }
};

const handleReloadAllFailed = async () => {
    const dirNames = Object.keys(failedPluginsDict.value);
    if (dirNames.length === 0) {
        toast("没有需要重载的失败插件", "info");
        return;
    }

    loading_.value = true;
    try {
        const promises = dirNames.map(dir => 
            axios.post("/api/plugin/reload-failed", { dir_name: dir })
        );
        await Promise.all(promises);
        
        toast("已尝试重载所有失败插件", "success");
        
        // 清空 message 关闭对话框
        extension_data.message = "";
        
        // 刷新列表
        await getExtensions();
        
    } catch (e) {
        console.error("重载失败：", e);
        toast("批量重载过程中出现错误", "error");
    } finally {
        loading_.value = false;
    }
};

const checkUpdate = () => {
  const onlinePluginsMap = new Map();
  const onlinePluginsNameMap = new Map();

  pluginMarketData.value.forEach((plugin) => {
    if (plugin.repo) {
      onlinePluginsMap.set(plugin.repo.toLowerCase(), plugin);
    }
    onlinePluginsNameMap.set(plugin.name, plugin);
  });

  const data = Array.isArray(extension_data?.data) ? extension_data.data : [];
  data.forEach((extension) => {
    const repoKey = extension.repo?.toLowerCase();
    const onlinePlugin = repoKey ? onlinePluginsMap.get(repoKey) : null;
    const onlinePluginByName = onlinePluginsNameMap.get(extension.name);
    const matchedPlugin = onlinePlugin || onlinePluginByName;

    if (matchedPlugin) {
      extension.online_version = matchedPlugin.version;
      extension.has_update =
        extension.version !== matchedPlugin.version &&
        matchedPlugin.version !== tm("status.unknown");
    } else {
      extension.has_update = false;
    }
  });
};

const uninstallExtension = async (
  extension_name,
  optionsOrSkipConfirm = false,
) => {
  let deleteConfig = false;
  let deleteData = false;
  let skipConfirm = false;

  // 处理参数：可能是布尔值（旧的 skipConfirm）或对象（新的选项）
  if (typeof optionsOrSkipConfirm === "boolean") {
    skipConfirm = optionsOrSkipConfirm;
  } else if (
    typeof optionsOrSkipConfirm === "object" &&
    optionsOrSkipConfirm !== null
  ) {
    deleteConfig = optionsOrSkipConfirm.deleteConfig || false;
    deleteData = optionsOrSkipConfirm.deleteData || false;
    skipConfirm = true; // 如果传递了选项对象，说明已经确认过了
  }

  // 如果没有跳过确认且没有传递选项对象，显示自定义卸载对话框
  if (!skipConfirm) {
    pluginToUninstall.value = extension_name;
    showUninstallDialog.value = true;
    return; // 等待对话框回调
  }

  // 执行卸载
  toast(tm("messages.uninstalling") + " " + extension_name, "primary");
  try {
    const res = await axios.post("/api/plugin/uninstall", {
      name: extension_name,
      delete_config: deleteConfig,
      delete_data: deleteData,
    });
    if (res.data.status === "error") {
      toast(res.data.message, "error");
      return;
    }
    Object.assign(extension_data, res.data);
    toast(res.data.message, "success");
    getExtensions();
  } catch (err) {
    toast(err, "error");
  }
};

// 处理卸载确认对话框的确认事件
const handleUninstallConfirm = (options) => {
  if (pluginToUninstall.value) {
    uninstallExtension(pluginToUninstall.value, options);
    pluginToUninstall.value = null;
  }
};

const updateExtension = async (extension_name, forceUpdate = false) => {
  // 查找插件信息
  const data = Array.isArray(extension_data?.data) ? extension_data.data : [];
  const ext = data.find((e) => e.name === extension_name);

  // 如果没有检测到更新且不是强制更新，则弹窗确认
  if (!ext?.has_update && !forceUpdate) {
    forceUpdateDialog.extensionName = extension_name;
    forceUpdateDialog.show = true;
    return;
  }

  loadingDialog.title = tm("status.loading");
  loadingDialog.show = true;
  try {
    const res = await axios.post("/api/plugin/update", {
      name: extension_name,
      proxy: getSelectedGitHubProxy(),
    });

    if (res.data.status === "error") {
      onLoadingDialogResult(2, res.data.message, -1);
      return;
    }

    Object.assign(extension_data, res.data);
    onLoadingDialogResult(1, res.data.message);
    setTimeout(async () => {
      toast(tm("messages.refreshing"), "info", 2000);
      try {
        await getExtensions();
        toast(tm("messages.refreshSuccess"), "success");

        // 更新完成后弹出更新日志
        viewChangelog({
          name: extension_name,
          repo: ext?.repo || null,
        });
      } catch (error) {
        const errorMsg =
          error.response?.data?.message || error.message || String(error);
        toast(`${tm("messages.refreshFailed")}: ${errorMsg}`, "error");
      }
    }, 1000);
  } catch (err) {
    toast(err, "error");
  }
};

// 确认强制更新
// 显示更新全部插件确认对话框
const showUpdateAllConfirm = () => {
  if (updatableExtensions.value.length === 0) return;
  updateAllConfirmDialog.show = true;
};

// 确认更新全部插件
const confirmUpdateAll = () => {
  updateAllConfirmDialog.show = false;
  updateAllExtensions();
};

// 取消更新全部插件
const cancelUpdateAll = () => {
  updateAllConfirmDialog.show = false;
};

const confirmForceUpdate = () => {
  const name = forceUpdateDialog.extensionName;
  forceUpdateDialog.show = false;
  forceUpdateDialog.extensionName = "";
  updateExtension(name, true);
};

const updateAllExtensions = async () => {
  if (updatingAll.value || updatableExtensions.value.length === 0) return;
  updatingAll.value = true;
  loadingDialog.title = tm("status.loading");
  loadingDialog.statusCode = 0;
  loadingDialog.result = "";
  loadingDialog.show = true;

  const targets = updatableExtensions.value.map((ext) => ext.name);
  try {
    const res = await axios.post("/api/plugin/update-all", {
      names: targets,
      proxy: getSelectedGitHubProxy(),
    });

    if (res.data.status === "error") {
      onLoadingDialogResult(
        2,
        res.data.message ||
          tm("messages.updateAllFailed", {
            failed: targets.length,
            total: targets.length,
          }),
        -1,
      );
      return;
    }

    const results = res.data.data?.results || [];
    const failures = results.filter((r) => r.status !== "ok");
    try {
      await getExtensions();
    } catch (err) {
      const errorMsg =
        err.response?.data?.message || err.message || String(err);
      failures.push({ name: "refresh", status: "error", message: errorMsg });
    }

    if (failures.length === 0) {
      onLoadingDialogResult(1, tm("messages.updateAllSuccess"));
    } else {
      const failureText = tm("messages.updateAllFailed", {
        failed: failures.length,
        total: targets.length,
      });
      const detail = failures.map((f) => `${f.name}: ${f.message}`).join("\n");
      onLoadingDialogResult(2, `${failureText}\n${detail}`, -1);
    }
  } catch (err) {
    const errorMsg = err.response?.data?.message || err.message || String(err);
    onLoadingDialogResult(2, errorMsg, -1);
  } finally {
    updatingAll.value = false;
  }
};

const pluginOn = async (extension) => {
  try {
    const res = await axios.post("/api/plugin/on", { name: extension.name });
    if (res.data.status === "error") {
      toast(res.data.message, "error");
      return;
    }
    toast(res.data.message, "success");
    await getExtensions();

    await checkAndPromptConflicts();
  } catch (err) {
    toast(err, "error");
  }
};

const pluginOff = async (extension) => {
  try {
    const res = await axios.post("/api/plugin/off", { name: extension.name });
    if (res.data.status === "error") {
      toast(res.data.message, "error");
      return;
    }
    toast(res.data.message, "success");
    getExtensions();
  } catch (err) {
    toast(err, "error");
  }
};

const openExtensionConfig = async (extension_name) => {
  curr_namespace.value = extension_name;
  configDialog.value = true;
  try {
    const res = await axios.get(
      "/api/config/get?plugin_name=" + extension_name,
    );
    extension_config.metadata = res.data.data.metadata;
    extension_config.config = res.data.data.config;
  } catch (err) {
    toast(err, "error");
  }
};

const updateConfig = async () => {
  try {
    const res = await axios.post(
      "/api/config/plugin/update?plugin_name=" + curr_namespace.value,
      extension_config.config,
    );
    if (res.data.status === "ok") {
      toast(res.data.message, "success");
    } else {
      toast(res.data.message, "error");
    }
    configDialog.value = false;
    extension_config.metadata = {};
    extension_config.config = {};
    getExtensions();
  } catch (err) {
    toast(err, "error");
  }
};

const showPluginInfo = (plugin) => {
  selectedPlugin.value = plugin;
  showPluginInfoDialog.value = true;
};

const reloadPlugin = async (plugin_name) => {
  try {
    const res = await axios.post("/api/plugin/reload", { name: plugin_name });
    await getExtensions();
    if (res.data.status === "error") {
      toast(res.data.message, "error");
      return;
    }
    toast(tm("messages.reloadSuccess"), "success");
    //getExtensions();
  } catch (err) {
    toast(err, "error");
  }
};

const viewReadme = (plugin) => {
  readmeDialog.pluginName = plugin.name;
  readmeDialog.repoUrl = plugin.repo;
  readmeDialog.show = true;
};

// 查看更新日志
const viewChangelog = (plugin) => {
  changelogDialog.pluginName = plugin.name;
  changelogDialog.repoUrl = plugin.repo;
  changelogDialog.show = true;
};

// 为表格视图创建一个处理安装插件的函数
const handleInstallPlugin = async (plugin) => {
  if (plugin.tags && plugin.tags.includes("danger")) {
    selectedDangerPlugin.value = plugin;
    dangerConfirmDialog.value = true;
  } else {
    selectedMarketInstallPlugin.value = plugin;
    extension_url.value = plugin.repo;
    dialog.value = true;
    uploadTab.value = "url";
  }
};

// 确认安装危险插件
const confirmDangerInstall = () => {
  if (selectedDangerPlugin.value) {
    selectedMarketInstallPlugin.value = selectedDangerPlugin.value;
    extension_url.value = selectedDangerPlugin.value.repo;
    dialog.value = true;
    uploadTab.value = "url";
  }
  dangerConfirmDialog.value = false;
  selectedDangerPlugin.value = null;
};

// 取消安装危险插件
const cancelDangerInstall = () => {
  dangerConfirmDialog.value = false;
  selectedDangerPlugin.value = null;
};

// 自定义插件源管理方法
const loadCustomSources = async () => {
  try {
    const res = await axios.get("/api/plugin/source/get");
    if (res.data.status === "ok") {
      customSources.value = res.data.data;
    } else {
      toast(res.data.message, "error");
    }
  } catch (e) {
    console.warn("Failed to load custom sources:", e);
    customSources.value = [];
  }

  // 加载当前选中的插件源
  const currentSource = localStorage.getItem("selectedPluginSource");
  if (currentSource) {
    selectedSource.value = currentSource;
  }
};

const saveCustomSources = async () => {
  try {
    const res = await axios.post("/api/plugin/source/save", {
      sources: customSources.value,
    });
    if (res.data.status !== "ok") {
      toast(res.data.message, "error");
    }
  } catch (e) {
    toast(e, "error");
  }
};

const addCustomSource = () => {
  editingSource.value = false;
  originalSourceUrl.value = "";
  sourceName.value = "";
  sourceUrl.value = "";
  showSourceDialog.value = true;
};

const selectPluginSource = (sourceUrl) => {
  selectedSource.value = sourceUrl;
  if (sourceUrl) {
    localStorage.setItem("selectedPluginSource", sourceUrl);
  } else {
    localStorage.removeItem("selectedPluginSource");
  }
  // 重新加载插件市场数据
  refreshPluginMarket();
};

// 获取当前选中的源对象
const selectedSourceObj = computed(() => {
  if (!selectedSource.value) return null;
  return (
    customSources.value.find((s) => s.url === selectedSource.value) || null
  );
});

const editCustomSource = (source) => {
  if (!source) return;
  editingSource.value = true;
  originalSourceUrl.value = source.url;
  sourceName.value = source.name;
  sourceUrl.value = source.url;
  showSourceDialog.value = true;
};

const removeCustomSource = (source) => {
  if (!source) return;
  sourceToRemove.value = source;
  showRemoveSourceDialog.value = true;
};

const confirmRemoveSource = () => {
  if (sourceToRemove.value) {
    customSources.value = customSources.value.filter(
      (s) => s.url !== sourceToRemove.value.url,
    );
    saveCustomSources();

    // 如果删除的是当前选中的源，切换到默认源
    if (selectedSource.value === sourceToRemove.value.url) {
      selectedSource.value = null;
      localStorage.removeItem("selectedPluginSource");
      // 重新加载插件市场数据
      refreshPluginMarket();
    }

    toast(tm("market.sourceRemoved"), "success");
    showRemoveSourceDialog.value = false;
    sourceToRemove.value = null;
  }
};

const saveCustomSource = () => {
  const normalizedUrl = sourceUrl.value.trim();

  if (!sourceName.value.trim() || !normalizedUrl) {
    toast(tm("messages.fillSourceNameAndUrl"), "error");
    return;
  }

  // 检查 URL 格式
  try {
    new URL(normalizedUrl);
  } catch (e) {
    toast(tm("messages.invalidUrl"), "error");
    return;
  }

  if (editingSource.value) {
    // 编辑模式：更新现有源
    const index = customSources.value.findIndex(
      (s) => s.url === originalSourceUrl.value,
    );
    if (index !== -1) {
      customSources.value[index] = {
        name: sourceName.value.trim(),
        url: normalizedUrl,
      };

      // 如果编辑的是当前选中的源，更新选中源
      if (selectedSource.value === originalSourceUrl.value) {
        selectedSource.value = normalizedUrl;
        localStorage.setItem("selectedPluginSource", selectedSource.value);
        // 重新加载插件市场数据
        refreshPluginMarket();
      }
    }
  } else {
    // 添加模式：检查是否已存在
    if (customSources.value.some((source) => source.url === normalizedUrl)) {
      toast(tm("market.sourceExists"), "error");
      return;
    }

    customSources.value.push({
      name: sourceName.value.trim(),
      url: normalizedUrl,
    });
  }

  saveCustomSources();
  toast(
    editingSource.value ? tm("market.sourceUpdated") : tm("market.sourceAdded"),
    "success",
  );

  // 重置表单
  sourceName.value = "";
  sourceUrl.value = "";
  editingSource.value = false;
  originalSourceUrl.value = "";
  showSourceDialog.value = false;
};

// 插件市场显示完整插件名称
const trimExtensionName = () => {
  if (!Array.isArray(pluginMarketData.value)) return;
  pluginMarketData.value.forEach((plugin) => {
    if (plugin.name) {
      let name = plugin.name.trim().toLowerCase();
      if (name.startsWith("astrbot_plugin_")) {
        plugin.trimmedName = name.substring(15);
      } else if (name.startsWith("astrbot_") || name.startsWith("astrbot-")) {
        plugin.trimmedName = name.substring(8);
      } else plugin.trimmedName = plugin.name;
    }
  });
};

const checkAlreadyInstalled = () => {
  const data = Array.isArray(extension_data?.data) ? extension_data.data : [];
  if (!Array.isArray(pluginMarketData.value)) return;

  const installedRepos = new Set(data.map((ext) => ext.repo?.toLowerCase()));
  const installedNames = new Set(data.map((ext) => ext.name));
  const installedByRepo = new Map(
    data
      .filter((ext) => ext.repo)
      .map((ext) => [ext.repo.toLowerCase(), ext]),
  );
  const installedByName = new Map(data.map((ext) => [ext.name, ext]));

  for (let i = 0; i < pluginMarketData.value.length; i++) {
    const plugin = pluginMarketData.value[i];
    const matchedInstalled =
      (plugin.repo && installedByRepo.get(plugin.repo.toLowerCase())) ||
      installedByName.get(plugin.name);

    // 兜底：市场源未提供字段时，回填本地已安装插件中的元数据，便于在市场页直接展示
    if (matchedInstalled) {
      if (
        (!Array.isArray(plugin.support_platforms) ||
          plugin.support_platforms.length === 0) &&
        Array.isArray(matchedInstalled.support_platforms)
      ) {
        plugin.support_platforms = matchedInstalled.support_platforms;
      }
      if (!plugin.astrbot_version && matchedInstalled.astrbot_version) {
        plugin.astrbot_version = matchedInstalled.astrbot_version;
      }
    }

    plugin.installed =
      installedRepos.has(plugin.repo?.toLowerCase()) ||
      installedNames.has(plugin.name);
  }

  let installed = [];
  let notInstalled = [];
  for (let i = 0; i < pluginMarketData.value.length; i++) {
    if (pluginMarketData.value[i].installed) {
      installed.push(pluginMarketData.value[i]);
    } else {
      notInstalled.push(pluginMarketData.value[i]);
    }
  }
  pluginMarketData.value = notInstalled.concat(installed);
};

const showVersionCompatibilityWarning = (message) => {
  versionCompatibilityDialog.message = message;
  versionCompatibilityDialog.show = true;
};

const continueInstallIgnoringVersionWarning = async () => {
  versionCompatibilityDialog.show = false;
  await newExtension(true);
};

const cancelInstallOnVersionWarning = () => {
  versionCompatibilityDialog.show = false;
};

const newExtension = async (ignoreVersionCheck = false) => {
  if (extension_url.value === "" && upload_file.value === null) {
    toast(tm("messages.fillUrlOrFile"), "error");
    return;
  }

  if (extension_url.value !== "" && upload_file.value !== null) {
    toast(tm("messages.dontFillBoth"), "error");
    return;
  }
  loading_.value = true;
  loadingDialog.title = tm("status.loading");
  loadingDialog.show = true;
  if (upload_file.value !== null) {
    toast(tm("messages.installing"), "primary");
    const formData = new FormData();
    formData.append("file", upload_file.value);
    formData.append("ignore_version_check", String(ignoreVersionCheck));
    axios
      .post("/api/plugin/install-upload", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      })
      .then(async (res) => {
        loading_.value = false;
        if (
          res.data.status === "warning" &&
          res.data.data?.warning_type === "astrbot_version_incompatible"
        ) {
          onLoadingDialogResult(2, res.data.message, -1);
          showVersionCompatibilityWarning(res.data.message);
          return;
        }
        if (res.data.status === "error") {
          onLoadingDialogResult(2, res.data.message, -1);
          return;
        }
        upload_file.value = null;
        onLoadingDialogResult(1, res.data.message);
        dialog.value = false;
        await getExtensions();

        viewReadme({
          name: res.data.data.name,
          repo: res.data.data.repo || null,
        });

        await checkAndPromptConflicts();
      })
      .catch((err) => {
        loading_.value = false;
        onLoadingDialogResult(2, err, -1);
      });
  } else {
    toast(
      tm("messages.installingFromUrl") + " " + extension_url.value,
      "primary",
    );
    axios
      .post("/api/plugin/install", {
        url: extension_url.value,
        proxy: getSelectedGitHubProxy(),
        ignore_version_check: ignoreVersionCheck,
      })
      .then(async (res) => {
        loading_.value = false;
        if (
          res.data.status === "warning" &&
          res.data.data?.warning_type === "astrbot_version_incompatible"
        ) {
          onLoadingDialogResult(2, res.data.message, -1);
          showVersionCompatibilityWarning(res.data.message);
          return;
        }
        toast(res.data.message, res.data.status === "ok" ? "success" : "error");
        if (res.data.status === "error") {
          onLoadingDialogResult(2, res.data.message, -1);
          return;
        }
        extension_url.value = "";
        onLoadingDialogResult(1, res.data.message);
        dialog.value = false;
        await getExtensions();

        viewReadme({
          name: res.data.data.name,
          repo: res.data.data.repo || null,
        });

        await checkAndPromptConflicts();
      })
      .catch((err) => {
        loading_.value = false;
        toast(tm("messages.installFailed") + " " + err, "error");
        onLoadingDialogResult(2, err, -1);
      });
  }
};

const normalizePlatformList = (platforms) => {
  if (!Array.isArray(platforms)) return [];
  return platforms.filter((item) => typeof item === "string");
};

const getPlatformDisplayList = (platforms) => {
  return normalizePlatformList(platforms).map((platformId) =>
    getPlatformDisplayName(platformId),
  );
};

const resolveSelectedInstallPlugin = () => {
  if (
    selectedMarketInstallPlugin.value &&
    selectedMarketInstallPlugin.value.repo === extension_url.value
  ) {
    return selectedMarketInstallPlugin.value;
  }
  return pluginMarketData.value.find((plugin) => plugin.repo === extension_url.value) || null;
};

const selectedInstallPlugin = computed(() => resolveSelectedInstallPlugin());

const checkInstallCompatibility = async () => {
  installCompat.checked = false;
  installCompat.compatible = true;
  installCompat.message = "";

  const plugin = selectedInstallPlugin.value;
  if (!plugin?.astrbot_version || uploadTab.value !== "url") {
    return;
  }

  try {
    const res = await axios.post("/api/plugin/check-compat", {
      astrbot_version: plugin.astrbot_version,
    });
    if (res.data.status === "ok") {
      installCompat.checked = true;
      installCompat.compatible = !!res.data.data?.compatible;
      installCompat.message = res.data.data?.message || "";
    }
  } catch (err) {
    console.debug("Failed to check plugin compatibility:", err);
  }
};

// 刷新插件市场数据
const refreshPluginMarket = async () => {
  refreshingMarket.value = true;
  try {
    // 强制刷新插件市场数据
    const data = await commonStore.getPluginCollections(
      true,
      selectedSource.value,
    );
    pluginMarketData.value = data;
    trimExtensionName();
    checkAlreadyInstalled();
    checkUpdate();
    refreshRandomPlugins();
    currentPage.value = 1; // 重置到第一页

    toast(tm("messages.refreshSuccess"), "success");
  } catch (err) {
    toast(tm("messages.refreshFailed") + " " + err, "error");
  } finally {
    refreshingMarket.value = false;
  }
};

// 生命周期
onMounted(async () => {
  if (!syncTabFromHash(getLocationHash())) {
    if (typeof window !== "undefined") {
      window.location.hash = `#${activeTab.value}`;
    }
  }
  await getExtensions();

  // 加载自定义插件源
  loadCustomSources();

  // 检查是否有 open_config 参数
  let urlParams;
  if (window.location.hash) {
    // For hash mode (#/path?param=value)
    const hashQuery = window.location.hash.split("?")[1] || "";
    urlParams = new URLSearchParams(hashQuery);
  } else {
    // For history mode (/path?param=value)
    urlParams = new URLSearchParams(window.location.search);
  }
  console.log("URL Parameters:", urlParams.toString());
  const plugin_name = urlParams.get("open_config");
  if (plugin_name) {
    console.log(`Opening config for plugin: ${plugin_name}`);
    openExtensionConfig(plugin_name);
  }

  try {
    const data = await commonStore.getPluginCollections(
      false,
      selectedSource.value,
    );
    pluginMarketData.value = data;
    trimExtensionName();
    checkAlreadyInstalled();
    checkUpdate();
    refreshRandomPlugins();
  } catch (err) {
    toast(tm("messages.getMarketDataFailed") + " " + err, "error");
  }
});

// 处理语言切换事件，重新加载插件配置以获取插件的 i18n 数据
const handleLocaleChange = () => {
  // 如果配置对话框是打开的，重新加载当前插件的配置
  if (configDialog.value && currentConfigPlugin.value) {
    openExtensionConfig(currentConfigPlugin.value);
  }
};

// 监听语言切换事件
window.addEventListener("astrbot-locale-changed", handleLocaleChange);

// 清理事件监听器
onUnmounted(() => {
  window.removeEventListener("astrbot-locale-changed", handleLocaleChange);
});

// 搜索防抖处理
let searchDebounceTimer = null;
watch(marketSearch, (newVal) => {
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer);
  }

  searchDebounceTimer = setTimeout(() => {
    debouncedMarketSearch.value = newVal;
    // 搜索时重置到第一页
    currentPage.value = 1;
  }, 300); // 300ms 防抖延迟
});

// 监听显示模式变化并保存到 localStorage
watch(isListView, (newVal) => {
  if (typeof window !== "undefined" && window.localStorage) {
    localStorage.setItem("pluginListViewMode", String(newVal));
  }
});

watch(
  [() => dialog.value, () => extension_url.value, () => uploadTab.value],
  async ([dialogOpen, _, currentUploadTab]) => {
    if (!dialogOpen || currentUploadTab !== "url") {
      installCompat.checked = false;
      installCompat.compatible = true;
      installCompat.message = "";
      return;
    }
    await checkInstallCompatibility();
  },
);

watch(
  () => route.fullPath,
  () => {
    const tab = extractTabFromHash(getLocationHash());
    if (isValidTab(tab) && tab !== activeTab.value) {
      activeTab.value = tab;
    }
  },
);

watch(activeTab, (newTab) => {
  if (!isValidTab(newTab)) return;
  const currentTab = extractTabFromHash(getLocationHash());
  if (currentTab === newTab) return;
  const hash = getLocationHash();
  const lastHashIndex = hash.lastIndexOf("#");
  const nextHash =
    lastHashIndex > 0 ? `${hash.slice(0, lastHashIndex)}#${newTab}` : `#${newTab}`;
  if (typeof window !== "undefined") {
    window.location.hash = nextHash;
  }
});
</script>

<template>
  <v-row>
    <v-col cols="12" md="12">
      <v-card variant="flat" style="background-color: transparent">
        <!-- 标签页 -->
        <v-card-text style="padding: 0px 12px">
          <!-- 已安装插件标签页内容 -->
          <InstalledPluginsTab :state="pageState" />

          <!-- 指令面板标签页内容 -->
          <v-tab-item v-show="activeTab === 'components'">
            <div class="mb-4 pt-4 pb-4">
              <div class="d-flex align-center flex-wrap" style="gap: 12px">
                <h2 class="text-h2 mb-0">{{ tm("tabs.handlersOperation") }}</h2>
              </div>
            </div>
            <v-card
              class="rounded-lg"
              variant="flat"
              style="background-color: transparent"
            >
              <v-card-text class="pa-0">
                <ComponentPanel :active="activeTab === 'components'" />
              </v-card-text>
            </v-card>
          </v-tab-item>

          <!-- 已安装的 MCP 服务器标签页内容 -->
          <v-tab-item v-show="activeTab === 'mcp'">
            <div class="mb-4 pt-4 pb-4">
              <div class="d-flex align-center flex-wrap" style="gap: 12px">
                <h2 class="text-h2 mb-0">{{ tm("tabs.installedMcpServers") }}</h2>
              </div>
            </div>
            <v-card
              class="rounded-lg"
              variant="flat"
              style="background-color: transparent"
            >
              <v-card-text class="pa-0">
                <McpServersSection />
              </v-card-text>
            </v-card>
          </v-tab-item>

          <!-- Skills 标签页内容 -->
          <v-tab-item v-show="activeTab === 'skills'">
            <div class="mb-4 pt-4 pb-4">
              <div class="d-flex align-center flex-wrap" style="gap: 12px">
                <h2 class="text-h2 mb-0">{{ tm("tabs.skills") }}</h2>
              </div>
            </div>
            <v-card
              class="rounded-lg"
              variant="flat"
              style="background-color: transparent"
            >
              <v-card-text class="pa-0">
                <SkillsSection />
              </v-card-text>
            </v-card>
          </v-tab-item>

          <!-- 插件市场标签页内容 -->
          <MarketPluginsTab :state="pageState" />

          <v-row v-if="loading_">
            <v-col cols="12" class="d-flex justify-center">
              <v-progress-circular
                indeterminate
                color="primary"
                size="48"
              ></v-progress-circular>
            </v-col>
          </v-row>
        </v-card-text>
      </v-card>
    </v-col>

    <v-col v-if="activeTab === 'market'" cols="12" md="12">
      <div class="d-flex align-center justify-center mt-4 mb-4 gap-4">
        <v-btn
          variant="text"
          prepend-icon="mdi-book-open-variant"
          href="https://astrbot.app/dev/plugin.html"
          target="_blank"
          color="primary"
          class="text-none"
        >
          {{ tm("market.devDocs") }}
        </v-btn>
        <div
          style="
            height: 24px;
            width: 1px;
            background-color: rgba(var(--v-theme-on-surface), 0.12);
          "
        ></div>
        <v-btn
          variant="text"
          prepend-icon="mdi-github"
          href="https://github.com/AstrBotDevs/AstrBot_Plugins_Collection"
          target="_blank"
          color="primary"
          class="text-none"
        >
          {{ tm("market.submitRepo") }}
        </v-btn>
      </div>
    </v-col>
  </v-row>

  <!-- 配置对话框 -->
  <v-dialog v-model="configDialog" max-width="900">
    <v-card>
      <v-card-title class="text-h2 pa-4 pl-6 pb-0">{{
        tm("dialogs.config.title")
      }}</v-card-title>
      <v-card-text>
        <div style="max-height: 60vh; overflow-y: auto; padding-right: 8px">
          <AstrBotConfig
            v-if="extension_config.metadata"
            :metadata="extension_config.metadata"
            :iterable="extension_config.config"
            :metadataKey="curr_namespace"
            :pluginName="curr_namespace"
          />
          <p v-else>{{ tm("dialogs.config.noConfig") }}</p>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="blue-darken-1" variant="text" @click="updateConfig">{{
          tm("buttons.saveAndClose")
        }}</v-btn>
        <v-btn
          color="blue-darken-1"
          variant="text"
          @click="configDialog = false"
          >{{ tm("buttons.close") }}</v-btn
        >
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 加载对话框 -->
  <v-dialog v-model="loadingDialog.show" width="700" persistent>
    <v-card>
      <v-card-title class="text-h5">{{ loadingDialog.title }}</v-card-title>
      <v-card-text style="max-height: calc(100vh - 200px); overflow-y: auto">
        <v-progress-linear
          v-if="loadingDialog.statusCode === 0"
          indeterminate
          color="primary"
          class="mb-4"
        ></v-progress-linear>

        <div v-if="loadingDialog.statusCode !== 0" class="py-8 text-center">
          <v-icon
            class="mb-6"
            :color="loadingDialog.statusCode === 1 ? 'success' : 'error'"
            :icon="
              loadingDialog.statusCode === 1
                ? 'mdi-check-circle-outline'
                : 'mdi-alert-circle-outline'
            "
            size="128"
          ></v-icon>
          <div class="text-h4 font-weight-bold">{{ loadingDialog.result }}</div>
        </div>

        <div style="margin-top: 32px">
          <h3>{{ tm("dialogs.loading.logs") }}</h3>
          <ConsoleDisplayer
            historyNum="10"
            style="height: 200px; margin-top: 16px; margin-bottom: 24px"
          >
          </ConsoleDisplayer>
        </div>
      </v-card-text>

      <v-divider></v-divider>

      <v-card-actions class="pa-4">
        <v-spacer></v-spacer>
        <v-btn
          color="blue-darken-1"
          variant="text"
          @click="resetLoadingDialog"
          >{{ tm("buttons.close") }}</v-btn
        >
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 插件信息对话框 -->
  <v-dialog v-model="showPluginInfoDialog" width="1200">
    <v-card>
      <v-card-title class="text-h5"
        >{{ selectedPlugin.name }} {{ tm("buttons.viewInfo") }}</v-card-title
      >
      <v-card-text>
        <v-data-table
          style="font-size: 17px"
          :headers="plugin_handler_info_headers"
          :items="selectedPlugin.handlers"
          item-key="name"
        >
          <template v-slot:header.id="{ column }">
            <p style="font-weight: bold">{{ column.title }}</p>
          </template>
          <template v-slot:item.event_type="{ item }">
            {{ item.event_type }}
          </template>
          <template v-slot:item.desc="{ item }">
            {{ item.desc }}
          </template>
          <template v-slot:item.type="{ item }">
            <v-chip color="success">
              {{ item.type }}
            </v-chip>
          </template>
          <template v-slot:item.cmd="{ item }">
            <span style="font-weight: bold">{{ item.cmd }}</span>
          </template>
        </v-data-table>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn
          color="blue-darken-1"
          variant="text"
          @click="showPluginInfoDialog = false"
          >{{ tm("buttons.close") }}</v-btn
        >
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-snackbar
    :timeout="2000"
    elevation="24"
    :color="snack_success"
    v-model="snack_show"
  >
    {{ snack_message }}
  </v-snackbar>

  <ReadmeDialog
    v-model:show="readmeDialog.show"
    :plugin-name="readmeDialog.pluginName"
    :repo-url="readmeDialog.repoUrl"
  />

  <!-- 插件更新日志对话框（复用 ReadmeDialog） -->
  <ReadmeDialog
    v-model:show="changelogDialog.show"
    :plugin-name="changelogDialog.pluginName"
    :repo-url="changelogDialog.repoUrl"
    mode="changelog"
  />

  <!-- 卸载插件确认对话框（列表模式用） -->
  <UninstallConfirmDialog
    v-model="showUninstallDialog"
    @confirm="handleUninstallConfirm"
  />

  <!-- 更新全部插件确认对话框 -->
  <v-dialog v-model="updateAllConfirmDialog.show" max-width="420">
    <v-card class="rounded-lg">
      <v-card-title class="d-flex align-center pa-4">
        <v-icon color="warning" class="mr-2">mdi-update</v-icon>
        {{ tm("dialogs.updateAllConfirm.title") }}
      </v-card-title>
      <v-card-text>
        <p class="text-body-1">
          {{ tm("dialogs.updateAllConfirm.message", { count: updatableExtensions.length }) }}
        </p>
      </v-card-text>
      <v-card-actions class="pa-4">
        <v-spacer></v-spacer>
        <v-btn
          variant="text"
          @click="cancelUpdateAll"
        >{{ tm("buttons.cancel") }}</v-btn>
        <v-btn
          color="warning"
          variant="flat"
          @click="confirmUpdateAll"
        >{{ tm("dialogs.updateAllConfirm.confirm") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>


  <!-- 指令冲突提示对话框 -->
  <v-dialog v-model="conflictDialog.show" max-width="420">
    <v-card class="rounded-lg">
      <v-card-title class="d-flex align-center pa-4">
        <v-icon color="warning" class="mr-2">mdi-alert-circle</v-icon>
        {{ tm("conflicts.title") }}
      </v-card-title>
      <v-card-text class="px-4 pb-2">
        <div class="d-flex align-center mb-3">
          <v-chip
            color="warning"
            variant="tonal"
            size="large"
            class="font-weight-bold"
          >
            {{ conflictDialog.count }}
          </v-chip>
          <span class="ml-2 text-body-1">{{ tm("conflicts.pairs") }}</span>
        </div>
        <p
          class="text-body-2"
          style="color: rgba(var(--v-theme-on-surface), 0.7)"
        >
          {{ tm("conflicts.message") }}
        </p>
      </v-card-text>
      <v-card-actions class="pa-4 pt-2">
        <v-spacer></v-spacer>
        <v-btn variant="text" @click="conflictDialog.show = false">{{
          tm("conflicts.later")
        }}</v-btn>
        <v-btn color="warning" variant="flat" @click="handleConflictConfirm">
          {{ tm("conflicts.goToManage") }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 危险插件确认对话框 -->
  <v-dialog v-model="dangerConfirmDialog" width="500" persistent>
    <v-card>
      <v-card-title class="text-h5 d-flex align-center">
        <v-icon color="warning" class="mr-2">mdi-alert-circle</v-icon>
        {{ tm("dialogs.danger_warning.title") }}
      </v-card-title>
      <v-card-text>
        <div>{{ tm("dialogs.danger_warning.message") }}</div>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="grey" @click="cancelDangerInstall">
          {{ tm("dialogs.danger_warning.cancel") }}
        </v-btn>
        <v-btn color="warning" @click="confirmDangerInstall">
          {{ tm("dialogs.danger_warning.confirm") }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 版本不兼容警告对话框 -->
  <v-dialog v-model="versionCompatibilityDialog.show" width="520" persistent>
    <v-card>
      <v-card-title class="text-h5 d-flex align-center">
        <v-icon color="warning" class="mr-2">mdi-alert</v-icon>
        {{ tm("dialogs.versionCompatibility.title") }}
      </v-card-title>
      <v-card-text>
        <div class="mb-2">{{ tm("dialogs.versionCompatibility.message") }}</div>
        <div class="text-medium-emphasis">
          {{ versionCompatibilityDialog.message }}
        </div>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="grey" @click="cancelInstallOnVersionWarning">
          {{ tm("dialogs.versionCompatibility.cancel") }}
        </v-btn>
        <v-btn color="warning" @click="continueInstallIgnoringVersionWarning">
          {{ tm("dialogs.versionCompatibility.confirm") }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 上传插件对话框 -->
  <v-dialog v-model="dialog" width="500">
    <div
      class="v-card v-card--density-default rounded-lg v-card--variant-elevated"
    >
      <div class="v-card__loader">
        <v-progress-linear
          :indeterminate="loading_"
          color="primary"
          height="2"
          :active="loading_"
        ></v-progress-linear>
      </div>

      <v-card-title class="text-h3 pa-4 pb-0 pl-6">
        {{ tm("dialogs.install.title") }}
      </v-card-title>

      <div class="v-card-text">
        <v-tabs v-model="uploadTab" color="primary">
          <v-tab value="file">{{ tm("dialogs.install.fromFile") }}</v-tab>
          <v-tab value="url">{{ tm("dialogs.install.fromUrl") }}</v-tab>
        </v-tabs>

        <v-window v-model="uploadTab" class="mt-4">
          <v-window-item value="file">
            <div class="d-flex flex-column align-center justify-center pa-4">
              <v-file-input
                ref="fileInput"
                v-model="upload_file"
                :label="tm('upload.selectFile')"
                accept=".zip"
                hide-details
                hide-input
                class="d-none"
              ></v-file-input>

              <v-btn
                color="primary"
                size="large"
                prepend-icon="mdi-upload"
                @click="$refs.fileInput.click()"
                elevation="2"
              >
                {{ tm("buttons.selectFile") }}
              </v-btn>

              <div class="text-body-2 text-medium-emphasis mt-2">
                {{ tm("messages.supportedFormats") }}
              </div>

              <div v-if="upload_file" class="mt-4 text-center">
                <v-chip
                  color="primary"
                  size="large"
                  closable
                  @click:close="upload_file = null"
                >
                  {{ upload_file.name }}
                  <template v-slot:append>
                    <span class="text-caption ml-2"
                      >({{ (upload_file.size / 1024).toFixed(1) }}KB)</span
                    >
                  </template>
                </v-chip>
              </div>
            </div>
          </v-window-item>

          <v-window-item value="url">
            <div class="pa-4">
              <v-text-field
                v-model="extension_url"
                :label="tm('upload.enterUrl')"
                variant="outlined"
                prepend-inner-icon="mdi-link"
                hide-details
                class="rounded-lg mb-4"
                placeholder="https://github.com/username/repo"
              ></v-text-field>

              <div v-if="selectedInstallPlugin" class="mb-3">
                <v-chip
                  v-if="selectedInstallPlugin.astrbot_version"
                  size="small"
                  color="secondary"
                  variant="outlined"
                  class="mr-2 mb-2"
                >
                  {{ tm("card.status.astrbotVersion") }}:
                  {{ selectedInstallPlugin.astrbot_version }}
                </v-chip>
                <v-chip
                  v-if="normalizePlatformList(selectedInstallPlugin.support_platforms).length"
                  size="small"
                  color="info"
                  variant="outlined"
                  class="mb-2"
                >
                  {{ tm("card.status.supportPlatform") }}:
                  {{
                    getPlatformDisplayList(selectedInstallPlugin.support_platforms).join(
                      ", ",
                    )
                  }}
                </v-chip>
                <v-alert
                  v-if="
                    selectedInstallPlugin.astrbot_version &&
                    installCompat.checked &&
                    !installCompat.compatible
                  "
                  type="warning"
                  variant="tonal"
                  density="comfortable"
                  class="mt-2"
                >
                  {{ installCompat.message }}
                </v-alert>
              </div>

              <ProxySelector></ProxySelector>
            </div>
          </v-window-item>
        </v-window>
      </div>

      <div class="v-card-actions">
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="dialog = false">{{
          tm("buttons.cancel")
        }}</v-btn>
        <v-btn color="primary" variant="text" @click="newExtension">{{
          tm("buttons.install")
        }}</v-btn>
      </div>
    </div>
  </v-dialog>

  <!-- 插件源管理对话框 -->
  <v-dialog v-model="showSourceManagerDialog" width="640">
    <v-card>
      <v-card-title class="text-h3 pa-4 pl-6">{{
        tm("market.sourceManagement")
      }}</v-card-title>
      <v-card-text>
        <v-select
          :model-value="selectedSource || '__default__'"
          @update:model-value="
            selectPluginSource($event === '__default__' ? null : $event)
          "
          :items="sourceSelectItems"
          :label="tm('market.currentSource')"
          variant="outlined"
          prepend-inner-icon="mdi-source-branch"
          hide-details
          class="mb-4"
        ></v-select>

        <div class="d-flex align-center justify-space-between mb-2">
          <div class="text-subtitle-2">{{ tm("market.availableSources") }}</div>
          <v-btn
            size="small"
            color="primary"
            variant="tonal"
            prepend-icon="mdi-plus"
            @click="addCustomSource"
          >
            {{ tm("market.addSource") }}
          </v-btn>
        </div>

        <v-list density="compact" nav class="pa-0">
          <v-list-item
            rounded="md"
            color="primary"
            :active="selectedSource === null"
            @click="selectPluginSource(null)"
          >
            <template v-slot:prepend>
              <v-icon icon="mdi-shield-check" size="small" class="mr-2"></v-icon>
            </template>
            <v-list-item-title>{{ tm("market.defaultSource") }}</v-list-item-title>
          </v-list-item>

          <v-list-item
            v-for="source in customSources"
            :key="source.url"
            rounded="md"
            color="primary"
            :active="selectedSource === source.url"
            @click="selectPluginSource(source.url)"
          >
            <template v-slot:prepend>
              <v-icon icon="mdi-link-variant" size="small" class="mr-2"></v-icon>
            </template>
            <v-list-item-title>{{ source.name }}</v-list-item-title>
            <v-list-item-subtitle class="text-caption">{{
              source.url
            }}</v-list-item-subtitle>
            <template v-slot:append>
              <v-btn
                icon="mdi-pencil-outline"
                size="small"
                variant="text"
                color="medium-emphasis"
                @click.stop="editCustomSource(source)"
              ></v-btn>
              <v-btn
                icon="mdi-trash-can-outline"
                size="small"
                variant="text"
                color="error"
                @click.stop="removeCustomSource(source)"
              ></v-btn>
            </template>
          </v-list-item>
        </v-list>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="primary" variant="text" @click="showSourceManagerDialog = false">{{
          tm("buttons.close")
        }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 添加/编辑自定义插件源对话框 -->
  <v-dialog v-model="showSourceDialog" width="500">
    <v-card>
      <v-card-title class="text-h5">{{
        editingSource ? tm("market.editSource") : tm("market.addSource")
      }}</v-card-title>
      <v-card-text>
        <div class="pa-2">
          <v-text-field
            v-model="sourceName"
            :label="tm('market.sourceName')"
            variant="outlined"
            prepend-inner-icon="mdi-rename-box"
            hide-details
            class="mb-4"
            placeholder="我的插件源"
          ></v-text-field>

          <v-text-field
            v-model="sourceUrl"
            :label="tm('market.sourceUrl')"
            variant="outlined"
            prepend-inner-icon="mdi-link"
            hide-details
            placeholder="https://example.com/plugins.json"
          ></v-text-field>

          <div class="text-caption text-medium-emphasis mt-2">
            {{ tm("messages.enterJsonUrl") }}
          </div>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn color="grey" variant="text" @click="showSourceDialog = false">{{
          tm("buttons.cancel")
        }}</v-btn>
        <v-btn color="primary" variant="text" @click="saveCustomSource">{{
          tm("buttons.save")
        }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 删除插件源确认对话框 -->
  <v-dialog v-model="showRemoveSourceDialog" width="400">
    <v-card>
      <v-card-title class="text-h5 d-flex align-center">
        <v-icon color="warning" class="mr-2">mdi-alert-circle</v-icon>
        {{ tm("dialogs.uninstall.title") }}
      </v-card-title>
      <v-card-text>
        <div>{{ tm("market.confirmRemoveSource") }}</div>
        <div v-if="sourceToRemove" class="mt-2">
          <strong>{{ sourceToRemove.name }}</strong>
          <div class="text-caption">{{ sourceToRemove.url }}</div>
        </div>
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn
          color="grey"
          variant="text"
          @click="showRemoveSourceDialog = false"
          >{{ tm("buttons.cancel") }}</v-btn
        >
        <v-btn color="error" variant="text" @click="confirmRemoveSource">{{
          tm("buttons.deleteSource")
        }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- 强制更新确认对话框 -->
  <v-dialog v-model="forceUpdateDialog.show" max-width="420">
    <v-card class="rounded-lg">
      <v-card-title class="text-h6 d-flex align-center">
        <v-icon color="info" class="mr-2">mdi-information-outline</v-icon>
        {{ tm("dialogs.forceUpdate.title") }}
      </v-card-title>
      <v-card-text>
        {{ tm("dialogs.forceUpdate.message") }}
      </v-card-text>
      <v-card-actions>
        <v-spacer></v-spacer>
        <v-btn variant="text" @click="forceUpdateDialog.show = false">{{
          tm("buttons.cancel")
        }}</v-btn>
        <v-btn color="primary" variant="flat" @click="confirmForceUpdate">{{
          tm("dialogs.forceUpdate.confirm")
        }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.plugin-handler-item {
  margin-bottom: 10px;
  padding: 5px;
  border-radius: 5px;
  background-color: #f5f5f5;
}

.fab-button {
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.fab-button:hover {
  transform: translateY(-4px) scale(1.05);
  box-shadow: 0 12px 20px rgba(var(--v-theme-primary), 0.4);
}
</style>
