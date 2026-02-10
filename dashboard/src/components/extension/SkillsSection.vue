<template>
  <div class="skills-page">
    <v-container fluid class="pa-0" elevation="0">
      <v-row class="d-flex justify-space-between align-center px-4 py-3 pb-8">
        <div>
          <v-btn color="success" prepend-icon="mdi-upload" class="me-2" variant="tonal" @click="uploadDialog = true">
            {{ tm('skills.upload') }}
          </v-btn>
          <v-btn color="info" prepend-icon="mdi-fire" class="me-2" variant="tonal" @click="openHotDialog">
            {{ tm('skills.installFromMarket') }}
          </v-btn>
          <v-btn color="primary" prepend-icon="mdi-refresh" variant="tonal" @click="fetchSkills">
            {{ tm('skills.refresh') }}
          </v-btn>
        </div>
      </v-row>

      <div class="px-2 pb-2">
        <small style="color: grey;">{{ tm('skills.runtimeHint') }}</small>
      </div>

      <v-progress-linear v-if="loading" indeterminate color="primary"></v-progress-linear>

      <div v-else-if="skills.length === 0" class="text-center pa-8">
        <v-icon size="64" color="grey-lighten-1">mdi-folder-open</v-icon>
        <p class="text-grey mt-4">{{ tm('skills.empty') }}</p>
        <small class="text-grey">{{ tm('skills.emptyHint') }}</small>
      </div>

      <v-row v-else>
        <v-col v-for="skill in skills" :key="skill.name" cols="12" md="6" lg="4" xl="3">
          <item-card :item="skill" title-field="name" enabled-field="active" :loading="itemLoading[skill.name] || false"
            :show-edit-button="true" @toggle-enabled="toggleSkill" @delete="confirmDelete" @edit="openDetailDialog">
            <template v-slot:item-details="{ item }">
              <div class="text-caption text-medium-emphasis mb-2 skill-description">
                <v-icon size="small" class="me-1">mdi-text</v-icon>
                {{ item.description || tm('skills.noDescription') }}
              </div>
              <div class="text-caption text-medium-emphasis">
                <v-icon size="small" class="me-1">mdi-file-document</v-icon>
                {{ tm('skills.path') }}: {{ item.path }}
              </div>
            </template>
          </item-card>
        </v-col>
      </v-row>
    </v-container>

    <v-dialog v-model="uploadDialog" max-width="520px">
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6">{{ tm('skills.uploadDialogTitle') }}</v-card-title>
        <v-card-text>
          <small class="text-grey">{{ tm('skills.uploadHint') }}</small>
          <v-file-input v-model="uploadFile" accept=".zip" :label="tm('skills.selectFile')"
            prepend-icon="mdi-folder-zip-outline" variant="outlined" class="mt-4" :multiple="false" />
        </v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="uploadDialog = false">{{ tm('skills.cancel') }}</v-btn>
          <v-btn color="primary" :loading="uploading" :disabled="!uploadFile" @click="uploadSkill">
            {{ tm('skills.confirmUpload') }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteDialog" max-width="400px">
      <v-card>
        <v-card-title>{{ tm('skills.deleteTitle') }}</v-card-title>
        <v-card-text>{{ tm('skills.deleteMessage') }}</v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="deleteDialog = false">{{ tm('skills.cancel') }}</v-btn>
          <v-btn color="error" :loading="deleting" @click="deleteSkill">
            {{ t('core.common.itemCard.delete') }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="detailDialog" max-width="1400px">
      <v-card>
        <v-card-title class="dialog-header d-flex justify-space-between align-center pa-3">
          <span class="dialog-title">{{ tm('skills.detailDialogTitle') }}: {{ currentSkill?.name }}</span>
          <v-btn icon="mdi-close" variant="text" density="compact" size="small" @click="detailDialog = false"></v-btn>
        </v-card-title>
        <v-card-text class="pa-0 bg-surface">
          <v-container fluid class="pa-0" style="height: 600px;">
            <v-row style="height: 100%;">
              <v-col cols="4" class="file-tree-sidebar" style="height: 100%; overflow: auto;">
                <div class="file-tree-header">
                  <div class="text-subtitle-2 mb-0 pa-2">{{ tm('skills.detailFilesTitle') }}</div>
                </div>
                <div v-if="fileTree.length === 0" class="text-center pa-4 text-disabled">
                  <v-icon size="32" color="grey">mdi-folder-open</v-icon>
                  <p class="text-caption mt-2">No files found</p>
                </div>
                <div v-else class="file-tree">
                  <file-tree-item
                    v-for="item in fileTree"
                    :key="item.path"
                    :item="item"
                    :level="0"
                    :selected-path="currentFile"
                    @select="onFileSelect"
                  />
                </div>
              </v-col>
              <v-col cols="8" class="editor-column" style="height: 100%;">
                <div v-if="!currentFile" class="d-flex align-center justify-center h-100 text-disabled">
                  {{ tm('skills.detailNoFileSelected') }}
                </div>
                <div v-else class="editor-container">
                  <div class="editor-header d-flex align-center pa-2">
                    <v-icon size="small" class="me-2" color="grey">mdi-file-document</v-icon>
                    <span class="text-caption">{{ currentFile }}</span>
                  </div>
                  <div class="editor-wrapper">
                    <VueMonacoEditor
                      v-model:value="skillContent"
                      theme="vs-dark"
                      :language="getFileLanguage(currentFile)"
                      style="height: 520px;"
                      :options="{ minimap: { enabled: false }, scrollBeyondLastLine: false }"
                    />
                  </div>
                </div>
              </v-col>
            </v-row>
          </v-container>
        </v-card-text>
        <v-card-actions class="dialog-actions d-flex justify-end pa-2">
          <v-btn variant="text" size="small" @click="detailDialog = false">{{ tm('skills.cancel') }}</v-btn>
          <v-btn color="primary" size="small" :loading="saving" :disabled="!currentFile" @click="saveSkillDetail">
            {{ tm('buttons.save') }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="hotDialog" max-width="960px">
      <v-card>
        <v-card-title class="text-h4 pa-4 pb-0 pl-6">{{ tm('skills.hotDialogTitle') }}</v-card-title>
        <v-card-text>
          <v-btn-toggle v-model="marketView" mandatory class="mt-4 mb-3" density="comfortable" color="primary">
            <v-btn value="hot">{{ tm('skills.viewHot') }}</v-btn>
            <v-btn value="trending">{{ tm('skills.viewTrending24h') }}</v-btn>
            <v-btn value="all">{{ tm('skills.viewAllTime') }}</v-btn>
          </v-btn-toggle>

          <v-text-field v-model="hotSearch" :label="tm('skills.hotSearch')" clearable prepend-inner-icon="mdi-magnify"
            variant="outlined" :hint="tm('skills.searchHint')" persistent-hint class="mt-2" />

          <div class="d-flex justify-space-between align-center mb-2">
            <small class="text-grey">
              {{ marketSourceHint }}
            </small>
            <v-btn color="primary" variant="tonal" prepend-icon="mdi-refresh" :loading="hotLoading"
              @click="fetchHotSkills(true)">
              {{ tm('skills.hotRefresh') }}
            </v-btn>
          </div>

          <v-progress-linear v-if="hotLoading" indeterminate color="primary" class="mb-3" />

          <div v-else-if="!hotSkills || hotSkills.length === 0" class="text-center pa-8">
            <v-icon size="56" color="grey-lighten-1">mdi-fire-off</v-icon>
            <p class="text-grey mt-4">{{ isSearching ? tm('skills.searchEmpty') : tm('skills.hotEmpty') }}</p>
          </div>

          <v-list v-else class="hot-skills-list">
            <v-list-item v-for="skill in hotSkills" :key="getHotSkillKey(skill)">
              <template #title>
                <span class="font-weight-medium">{{ skill.name }}</span>
              </template>
              <template #subtitle>
                <div class="text-caption">
                  <div>{{ skill.source }} @{{ skill.skillId }}</div>
                  <div>
                    {{ tm('skills.hotInstalls') }}: {{ skill.installs }}
                    <span v-if="Number.isFinite(Number(skill.change))" class="ms-3">{{ tm('skills.hotChange') }}: {{
                      formatChange(skill.change)
                    }}</span>
                  </div>
                </div>
              </template>
              <template #append>
                <v-btn color="primary" size="small" :loading="hotItemLoading[getHotSkillKey(skill)] || false"
                  @click="installHotSkill(skill)">
                  {{ tm('skills.install') }}
                </v-btn>
              </template>
            </v-list-item>
          </v-list>
        </v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="hotDialog = false">{{ tm('skills.cancel') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :timeout="3000" :color="snackbar.color" elevation="24">
      {{ snackbar.message }}
    </v-snackbar>
  </div>
</template>

<script>
import axios from "axios";
import { ref, reactive, onMounted, computed, watch, onBeforeUnmount } from "vue";
import ItemCard from "@/components/shared/ItemCard.vue";
import { VueMonacoEditor } from '@guolao/vue-monaco-editor';
import { useI18n, useModuleI18n } from "@/i18n/composables";

// Recursive file tree item component - 侧边栏风格
const FileTreeItem = {
  name: "FileTreeItem",
  props: {
    item: { type: Object, required: true },
    level: { type: Number, default: 0 },
    selectedPath: { type: String, default: null },
  },
  emits: ["select"],
  setup(props, { emit }) {
    const isOpen = ref(true);
    const isDirectory = computed(() => props.item.type === "directory");
    const isSelected = computed(() => props.selectedPath === props.item.path);
    const indentWidth = computed(() => props.level * 16 + 8);

    const getFileIcon = (fileName) => {
      const ext = fileName.split('.').pop().toLowerCase();
      const iconMap = {
        'md': 'mdi-language-markdown',
        'py': 'mdi-language-python',
        'js': 'mdi-language-javascript',
        'ts': 'mdi-language-typescript',
        'json': 'mdi-code-json',
        'yaml': 'mdi-yaml',
        'yml': 'mdi-yaml',
        'xml': 'mdi-xml',
        'html': 'mdi-language-html5',
        'css': 'mdi-language-css3',
        'txt': 'mdi-text',
        'sh': 'mdi-console',
        'bash': 'mdi-console',
      };
      return iconMap[ext] || 'mdi-file-document-outline';
    };

    const toggle = () => {
      if (isDirectory.value) {
        isOpen.value = !isOpen.value;
      } else {
        emit("select", props.item.path);
      }
    };

    const onChildSelect = (path) => {
      emit("select", path);
    };

    return {
      isOpen,
      isDirectory,
      isSelected,
      indentWidth,
      getFileIcon,
      toggle,
      onChildSelect,
    };
  },
  template: `
    <div class="sidebar-tree-item">
      <div
        class="sidebar-tree-node"
        :class="{ 'is-selected': isSelected }"
        :style="{
          paddingLeft: indentWidth + 'px',
          backgroundColor: isSelected ? 'rgba(var(--v-theme-primary), 0.12)' : 'transparent',
          borderLeft: isSelected ? '3px solid rgb(var(--v-theme-primary))' : '3px solid transparent',
          marginLeft: isSelected ? '3px' : '6px',
          color: isSelected ? 'rgb(var(--v-theme-primary))' : ''
        }"
        @click="toggle"
      >
        <v-icon 
          v-if="isDirectory" 
          size="16" 
          class="sidebar-tree-arrow"
          :class="{ 'is-open': isOpen }"
          :style="{ color: isSelected ? 'rgb(var(--v-theme-primary))' : '' }"
        >
          mdi-chevron-right
        </v-icon>
        <v-icon 
          v-else
          size="16"
          class="sidebar-tree-arrow-placeholder"
        ></v-icon>
        <v-icon 
          size="18" 
          class="sidebar-tree-icon"
          :style="{ color: isSelected ? 'rgb(var(--v-theme-primary))' : '' }"
        >
          {{ isDirectory ? (isOpen ? 'mdi-folder-open' : 'mdi-folder') : getFileIcon(item.name) }}
        </v-icon>
        <span 
          class="sidebar-tree-label"
          :title="item.name"
          :style="{ 
            color: isSelected ? 'rgb(var(--v-theme-primary))' : '',
            fontWeight: isSelected ? '600' : '400'
          }"
        >{{ item.name }}</span>
      </div>
      <div v-if="isDirectory && isOpen && item.children" class="sidebar-tree-children">
        <file-tree-item
          v-for="child in item.children"
          :key="child.path"
          :item="child"
          :level="level + 1"
          :selected-path="selectedPath"
          @select="onChildSelect"
        />
      </div>
    </div>
  `,
};

export default {
  name: "SkillsSection",
  components: { ItemCard, VueMonacoEditor, FileTreeItem },
  setup() {
    const { t } = useI18n();
    const { tm } = useModuleI18n("features/extension");

    const skills = ref([]);
    const loading = ref(false);
    const uploading = ref(false);
    const uploadDialog = ref(false);
    const uploadFile = ref(null);
    const itemLoading = reactive({});
    const deleteDialog = ref(false);
    const deleting = ref(false);
    const skillToDelete = ref(null);
    const detailDialog = ref(false);
    const currentSkill = ref(null);
    const fileTree = ref([]);
    const currentFile = ref(null);
    const skillContent = ref("");
    const saving = ref(false);
    const hotDialog = ref(false);
    const hotSkills = ref([]);
    const hotLoading = ref(false);
    const hotSearch = ref("");
    const hotItemLoading = reactive({});
    const marketView = ref("hot");
    let searchTimer = null;
    const snackbar = reactive({ show: false, message: "", color: "success" });

    const showMessage = (message, color = "success") => {
      snackbar.message = message;
      snackbar.color = color;
      snackbar.show = true;
    };

    const getHotSkillKey = (skill) => `${skill.source}/${skill.skillId}`;
    const getSelectedGitHubProxy = () => {
      if (typeof window === "undefined" || !window.localStorage) return "";
      return localStorage.getItem("githubProxyRadioValue") === "1"
        ? localStorage.getItem("selectedGitHubProxy") || ""
        : "";
    };

    const isSearching = computed(() => hotSearch.value.trim().length >= 2);
    const marketSourceHint = computed(() => {
      if (isSearching.value) {
        return tm("skills.searchSourceHint");
      }
      if (marketView.value === "trending") {
        return tm("skills.trendingSourceHint");
      }
      if (marketView.value === "all") {
        return tm("skills.allSourceHint");
      }
      return tm("skills.hotSourceHint");
    });
    const formatChange = (value) => {
      const normalized = Number(value);
      if (!Number.isFinite(normalized)) {
        return "";
      }
      return normalized > 0 ? `+${normalized}` : String(normalized);
    };

    const fetchSkills = async () => {
      loading.value = true;
      try {
        const res = await axios.get("/api/skills");
        const payload = res.data?.data || [];
        if (Array.isArray(payload)) {
          skills.value = payload;
        } else {
          skills.value = payload.skills || [];
        }
      } catch (err) {
        showMessage(tm("skills.loadFailed"), "error");
      } finally {
        loading.value = false;
      }
    };

    const handleApiResponse = (res, successMessage, failureMessageDefault, onSuccess) => {
      if (res && res.data && res.data.status === "ok") {
        showMessage(successMessage, "success");
        if (onSuccess) onSuccess();
      } else {
        const msg = (res && res.data && res.data.message) || failureMessageDefault;
        showMessage(msg, "error");
      }
    };

    const fetchHotSkills = async (forceRefresh = false) => {
      hotLoading.value = true;
      try {
        let res = null;
        if (isSearching.value) {
          res = await axios.get("/api/skills/search", {
            params: {
              q: hotSearch.value.trim(),
              limit: 50,
            },
          });
        } else {
          res = await axios.get("/api/skills/hot", {
            params: {
              view: marketView.value,
              limit: 200,
              force_refresh: forceRefresh ? "true" : "false",
            },
          });
        }
        const payload = res.data?.data || {};
        if (Array.isArray(payload)) {
          hotSkills.value = payload;
        } else {
          hotSkills.value = payload.skills || [];
        }
      } catch (err) {
        showMessage(
          isSearching.value ? tm("skills.searchFailed") : tm("skills.hotLoadFailed"),
          "error"
        );
      } finally {
        hotLoading.value = false;
      }
    };

    const openHotDialog = async () => {
      hotDialog.value = true;
      if (!hotSkills.value.length) {
        await fetchHotSkills();
      }
    };

    const installHotSkill = async (skill) => {
      const key = getHotSkillKey(skill);
      hotItemLoading[key] = true;
      try {
        const res = await axios.post("/api/skills/install", {
          source: skill.source,
          skillId: skill.skillId,
          name: skill.name,
          proxy: getSelectedGitHubProxy(),
        });
        handleApiResponse(
          res,
          tm("skills.hotInstallSuccess"),
          tm("skills.hotInstallFailed"),
          async () => {
            await fetchSkills();
          }
        );
      } catch (err) {
        showMessage(tm("skills.hotInstallFailed"), "error");
      } finally {
        hotItemLoading[key] = false;
      }
    };

    const uploadSkill = async () => {
      if (!uploadFile.value) return;
      uploading.value = true;
      try {
        const formData = new FormData();
        const file = Array.isArray(uploadFile.value)
          ? uploadFile.value[0]
          : uploadFile.value;
        if (!file) {
          uploading.value = false;
          return;
        }
        formData.append("file", file);
        const res = await axios.post("/api/skills/upload", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        handleApiResponse(
          res,
          tm("skills.uploadSuccess"),
          tm("skills.uploadFailed"),
          async () => {
            uploadDialog.value = false;
            uploadFile.value = null;
            await fetchSkills();
          }
        );
      } catch (err) {
        showMessage(tm("skills.uploadFailed"), "error");
      } finally {
        uploading.value = false;
      }
    };

    const toggleSkill = async (skill) => {
      const nextActive = !skill.active;
      itemLoading[skill.name] = true;
      try {
        const res = await axios.post("/api/skills/update", {
          name: skill.name,
          active: nextActive,
        });
        handleApiResponse(
          res,
          tm("skills.updateSuccess"),
          tm("skills.updateFailed"),
          () => {
            skill.active = nextActive;
          }
        );
      } catch (err) {
        showMessage(tm("skills.updateFailed"), "error");
      } finally {
        itemLoading[skill.name] = false;
      }
    };

    const confirmDelete = (skill) => {
      skillToDelete.value = skill;
      deleteDialog.value = true;
    };

    const deleteSkill = async () => {
      if (!skillToDelete.value) return;
      deleting.value = true;
      try {
        const res = await axios.post("/api/skills/delete", {
          name: skillToDelete.value.name,
        });
        handleApiResponse(
          res,
          tm("skills.deleteSuccess"),
          tm("skills.deleteFailed"),
          async () => {
            deleteDialog.value = false;
            await fetchSkills();
          }
        );
      } catch (err) {
        showMessage(tm("skills.deleteFailed"), "error");
      } finally {
        deleting.value = false;
      }
    };

    const openDetailDialog = async (skill) => {
      currentSkill.value = skill;
      fileTree.value = [];
      currentFile.value = null;
      skillContent.value = "";
      detailDialog.value = true;
      try {
        const res = await axios.get("/api/skills/detail", {
          params: { name: skill.name }
        });
        if (res.data?.status === "ok") {
          fileTree.value = res.data.data.files || [];
          // Auto-select SKILL.md if it exists
          const findSkillMd = (items) => {
            for (const item of items) {
              if (item.type === 'file' && item.name === 'SKILL.md') {
                return item.path;
              }
              if (item.type === 'directory' && item.children) {
                const found = findSkillMd(item.children);
                if (found) return found;
              }
            }
            return null;
          };
          const skillMdPath = findSkillMd(fileTree.value);
          if (skillMdPath) {
            await loadFileContent(skillMdPath);
          }
        }
      } catch (err) {
        showMessage(tm("skills.loadDetailFailed"), "error");
      }
    };

    const onFileSelect = async (path) => {
      const findFileByPath = (items, targetPath) => {
        for (const item of items) {
          if (item.path === targetPath) return item;
          if (item.children) {
            const found = findFileByPath(item.children, targetPath);
            if (found) return found;
          }
        }
        return null;
      };
      const file = findFileByPath(fileTree.value, path);
      if (file && file.type === 'file') {
        await loadFileContent(path);
      }
    };

    const loadFileContent = async (filePath) => {
      if (!currentSkill.value) return;
      try {
        const res = await axios.get("/api/skills/file", {
          params: {
            name: currentSkill.value.name,
            file: filePath
          }
        });
        if (res.data?.status === "ok") {
          currentFile.value = filePath;
          skillContent.value = res.data.data.content || "";
        }
      } catch (err) {
        showMessage(tm("skills.loadFileFailed"), "error");
      }
    };

    const getFileLanguage = (fileName) => {
      const ext = fileName.split('.').pop().toLowerCase();
      const langMap = {
        'md': 'markdown',
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'json': 'json',
        'yaml': 'yaml',
        'yml': 'yaml',
        'xml': 'xml',
        'html': 'html',
        'css': 'css',
        'txt': 'plaintext',
      };
      return langMap[ext] || 'plaintext';
    };

    const saveSkillDetail = async () => {
      if (!currentSkill.value || !currentFile.value) return;
      saving.value = true;
      try {
        const res = await axios.post("/api/skills/update_detail", {
          name: currentSkill.value.name,
          file_path: currentFile.value,
          content: skillContent.value,
        });
        handleApiResponse(
          res,
          tm("skills.saveDetailSuccess"),
          tm("skills.saveDetailFailed"),
          async () => {
            await fetchSkills();
          }
        );
      } catch (err) {
        showMessage(tm("skills.saveDetailFailed"), "error");
      } finally {
        saving.value = false;
      }
    };

    watch(marketView, async () => {
      if (!hotDialog.value || isSearching.value) {
        return;
      }
      await fetchHotSkills();
    });

    watch(hotSearch, () => {
      if (!hotDialog.value) {
        return;
      }
      if (searchTimer) {
        clearTimeout(searchTimer);
      }
      searchTimer = setTimeout(async () => {
        await fetchHotSkills();
      }, 350);
    });

    onBeforeUnmount(() => {
      if (searchTimer) {
        clearTimeout(searchTimer);
      }
    });

    onMounted(fetchSkills);

    return {
      t,
      tm,
      skills,
      loading,
      uploadDialog,
      uploadFile,
      uploading,
      itemLoading,
      deleteDialog,
      deleting,
      detailDialog,
      currentSkill,
      fileTree,
      currentFile,
      skillContent,
      saving,
      hotDialog,
      hotLoading,
      hotSearch,
      hotSkills,
      hotItemLoading,
      marketView,
      isSearching,
      marketSourceHint,
      snackbar,
      getHotSkillKey,
      formatChange,
      fetchHotSkills,
      openHotDialog,
      installHotSkill,
      fetchSkills,
      uploadSkill,
      toggleSkill,
      confirmDelete,
      deleteSkill,
      openDetailDialog,
      onFileSelect,
      loadFileContent,
      getFileLanguage,
      saveSkillDetail,
    };
  },
};
</script>

<style scoped>
.skill-description {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hot-skills-list {
  max-height: 440px;
  overflow-y: auto;
}

.editor-wrapper {
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.file-tree-header {
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.file-tree-sidebar {
  background-color: rgb(var(--v-theme-containerBg));
  border-right: 1px solid rgb(var(--v-theme-border));
}

.file-tree-header {
  background-color: rgb(var(--v-theme-containerBg));
  border-bottom: 1px solid rgb(var(--v-theme-border));
}

.file-tree-header .text-subtitle-2 {
  color: rgb(var(--v-theme-primaryText));
  font-weight: 600;
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.5px;
  opacity: 0.7;
}

.file-tree {
  padding: 4px 0;
}

.sidebar-tree-item {
  width: 100%;
}

.sidebar-tree-node {
  display: flex;
  align-items: center;
  height: 28px;
  cursor: pointer;
  color: rgb(var(--v-theme-primaryText));
  font-size: 13px;
  user-select: none;
  transition: background-color 0.15s ease;
  border-radius: 4px;
  margin: 1px 6px;
  padding-right: 8px;
  opacity: 0.85;
}

.sidebar-tree-node:hover {
  background-color: rgba(var(--v-theme-primary), 0.1);
  opacity: 1;
}

.sidebar-tree-node.is-selected {
  background-color: rgba(var(--v-theme-primary), 0.12);
  color: rgb(var(--v-theme-primary));
  opacity: 1;
  border-left: 3px solid rgb(var(--v-theme-primary));
  margin-left: 3px;
}

.sidebar-tree-node.is-selected .sidebar-tree-icon,
.sidebar-tree-node.is-selected .sidebar-tree-label {
  color: rgb(var(--v-theme-primary));
  font-weight: 600;
}

.sidebar-tree-arrow {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  transition: transform 0.15s ease;
  margin-right: 2px;
}

.sidebar-tree-arrow.is-open {
  transform: rotate(90deg);
}

.sidebar-tree-arrow-placeholder {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  margin-right: 2px;
}

.sidebar-tree-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  margin-right: 6px;
}

.sidebar-tree-label {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 400;
}

.sidebar-tree-label.is-selected {
  font-weight: 600;
}

.sidebar-tree-children {
  width: 100%;
}

.dialog-header {
  background-color: rgb(var(--v-theme-containerBg));
  border-bottom: 1px solid rgb(var(--v-theme-border));
}

.dialog-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  opacity: 0.8;
}

.editor-column {
  background-color: rgb(var(--v-theme-background));
}

.editor-header {
  background-color: rgb(var(--v-theme-surface));
  border-bottom: 1px solid rgb(var(--v-theme-border));
}

.dialog-actions {
  background-color: rgb(var(--v-theme-containerBg));
  border-top: 1px solid rgb(var(--v-theme-border));
}

.editor-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.editor-header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
