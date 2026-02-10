<template>
  <div class="skills-page">
    <v-container fluid class="pa-0" elevation="0">
      <v-row class="d-flex justify-space-between align-center px-4 py-3 pb-4">
        <div>
          <v-btn
            v-if="mode === 'local'"
            color="success"
            prepend-icon="mdi-upload"
            class="me-2"
            variant="tonal"
            @click="uploadDialog = true"
          >
            {{ tm("skills.upload") }}
          </v-btn>
          <v-btn
            v-if="mode === 'local'"
            color="info"
            prepend-icon="mdi-fire"
            class="me-2"
            variant="tonal"
            @click="openHotDialog"
          >
            {{ tm("skills.installFromMarket") }}
          </v-btn>
          <v-btn color="primary" prepend-icon="mdi-refresh" variant="tonal" @click="refreshCurrentMode">
            {{ tm("skills.refresh") }}
          </v-btn>
        </div>
        <v-btn-toggle v-model="mode" mandatory divided density="comfortable">
          <v-btn value="local">{{ tm("skills.modeLocal") }}</v-btn>
          <v-btn value="neo" :disabled="!neoEnabled">{{ tm("skills.modeNeo") }}</v-btn>
        </v-btn-toggle>
      </v-row>

      <div v-if="mode === 'local'" class="px-2 pb-2 d-flex flex-column ga-2">
        <small style="color: grey">{{ tm("skills.runtimeHint") }}</small>
        <v-alert
          v-if="runtime === 'sandbox' && !sandboxCache.ready"
          type="info"
          variant="tonal"
          density="comfortable"
          border="start"
        >
          {{ tm("skills.sandboxDiscoveryPending") }}
        </v-alert>
      </div>

      <div v-if="mode === 'neo' && !neoEnabled" class="px-3 pb-3">
        <v-alert type="warning" variant="tonal" density="comfortable" border="start">
          {{ neoUnavailableMessage }}
        </v-alert>
      </div>

      <template v-if="mode === 'local'">
        <v-progress-linear v-if="loading" indeterminate color="primary"></v-progress-linear>

        <div v-else-if="skills.length === 0" class="text-center pa-8">
          <v-icon size="64" color="grey-lighten-1">mdi-folder-open</v-icon>
          <p class="text-grey mt-4">{{ tm("skills.empty") }}</p>
          <small class="text-grey">{{ tm("skills.emptyHint") }}</small>
        </div>

        <v-row v-else align="stretch">
          <v-col
            v-for="skill in skills"
            :key="skill.name"
            cols="12"
            md="6"
            lg="4"
            xl="3"
            class="d-flex"
          >
            <item-card
              :item="skill"
              title-field="name"
              enabled-field="active"
              :loading="itemLoading[skill.name] || false"
              :show-edit-button="!isSandboxPresetSkill(skill)"
              :disable-toggle="isSandboxPresetSkill(skill)"
              :disable-delete="isSandboxPresetSkill(skill)"
              @toggle-enabled="toggleSkill"
              @delete="confirmDelete"
              @edit="openDetailDialog"
            >
              <template #item-details="{ item }">
                <div class="d-flex align-center mb-2 ga-2 flex-wrap">
                  <v-chip
                    size="x-small"
                    variant="tonal"
                    :color="sourceTypeColor(item.source_type)"
                  >
                    {{ sourceTypeLabel(item.source_type) }}
                  </v-chip>
                  <div class="text-caption text-medium-emphasis skill-description">
                    <v-icon size="small" class="me-1">mdi-text</v-icon>
                    {{ item.description || tm("skills.noDescription") }}
                  </div>
                </div>
                <div class="text-caption text-medium-emphasis skill-path">
                  <v-icon size="small" class="me-1">mdi-file-document</v-icon>
                  {{ tm("skills.path") }}: {{ item.path }}
                </div>
              </template>
              <template #actions="{ item }">
                <v-btn
                  variant="tonal"
                  color="primary"
                  size="small"
                  rounded="xl"
                  :disabled="itemLoading[item.name] || false || isSandboxPresetSkill(item)"
                  @click="downloadSkill(item)"
                >
                  {{ tm("skills.download") }}
                </v-btn>
              </template>
            </item-card>
          </v-col>
        </v-row>
      </template>

      <template v-else-if="mode === 'neo' && neoEnabled">
        <v-card class="mx-3 mb-4 pa-4 neo-filter-card" variant="outlined">
          <div class="d-flex flex-wrap justify-space-between align-center ga-2 mb-3">
            <div>
              <div class="text-subtitle-1 font-weight-bold">Neo Skills</div>
              <div class="text-caption text-medium-emphasis">{{ tm("skills.neoFilterHint") }}</div>
            </div>
            <v-btn color="primary" prepend-icon="mdi-refresh" variant="flat" @click="fetchNeoData">
              {{ tm("skills.refresh") }}
            </v-btn>
          </div>

          <v-row class="ga-md-0 ga-2">
            <v-col cols="12" md="4">
              <v-text-field
                v-model="neoFilters.skill_key"
                :label="tm('skills.neoSkillKey')"
                prepend-inner-icon="mdi-key-outline"
                density="comfortable"
                hide-details
                variant="outlined"
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-select
                v-model="neoFilters.status"
                :label="tm('skills.neoStatus')"
                :items="candidateStatusItems"
                item-title="title"
                item-value="value"
                prepend-inner-icon="mdi-progress-check"
                density="comfortable"
                hide-details
                variant="outlined"
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-select
                v-model="neoFilters.stage"
                :label="tm('skills.neoStage')"
                :items="releaseStageItems"
                item-title="title"
                item-value="value"
                prepend-inner-icon="mdi-layers-outline"
                density="comfortable"
                hide-details
                variant="outlined"
              />
            </v-col>
          </v-row>
        </v-card>

        <v-progress-linear v-if="neoLoading" indeterminate color="primary"></v-progress-linear>

        <div class="mx-3 mb-3 d-flex flex-wrap ga-2">
          <v-chip size="small" color="primary" variant="tonal">Candidates: {{ neoCandidates.length }}</v-chip>
          <v-chip size="small" color="indigo" variant="tonal">Releases: {{ neoReleases.length }}</v-chip>
          <v-chip size="small" color="success" variant="tonal">Active: {{ activeReleaseCount }}</v-chip>
        </div>

        <v-card class="mx-3 mb-4 neo-table-card" variant="outlined">
          <v-card-title class="text-subtitle-1 font-weight-bold">{{ tm("skills.neoCandidates") }}</v-card-title>
          <v-data-table
            :headers="candidateHeaders"
            :items="neoCandidates"
            density="compact"
            :items-per-page="10"
            class="neo-data-table"
          >
            <template #item.latest_score="{ item }">
              {{ item.latest_score ?? "-" }}
            </template>
            <template #item.actions="{ item }">
              <div class="d-flex ga-1 flex-wrap">
                <v-btn size="x-small" color="success" variant="tonal" @click="evaluateCandidate(item, true)">
                  {{ tm("skills.neoPass") }}
                </v-btn>
                <v-btn size="x-small" color="warning" variant="tonal" @click="evaluateCandidate(item, false)">
                  {{ tm("skills.neoReject") }}
                </v-btn>
                <v-btn
                  size="x-small"
                  color="primary"
                  variant="tonal"
                  :loading="isCandidatePromoteLoading(item.id, 'canary')"
                  :disabled="isCandidatePromoting(item.id)"
                  @click="promoteCandidate(item, 'canary')"
                >
                  Canary
                </v-btn>
                <v-btn
                  size="x-small"
                  color="primary"
                  variant="tonal"
                  :loading="isCandidatePromoteLoading(item.id, 'stable')"
                  :disabled="isCandidatePromoting(item.id)"
                  @click="promoteCandidate(item, 'stable')"
                >
                  Stable
                </v-btn>
                <v-btn
                  size="x-small"
                  variant="tonal"
                  @click="viewPayload(item.payload_ref)"
                  :disabled="!item.payload_ref"
                >
                  Payload
                </v-btn>
                <v-btn
                  size="x-small"
                  color="error"
                  variant="tonal"
                  @click="deleteCandidate(item)"
                >
                  {{ tm("skills.neoDelete") }}
                </v-btn>
              </div>
            </template>
          </v-data-table>
        </v-card>

        <v-card class="mx-3 mb-4 neo-table-card" variant="outlined">
          <v-card-title class="text-subtitle-1 font-weight-bold">{{ tm("skills.neoReleases") }}</v-card-title>
          <v-data-table
            :headers="releaseHeaders"
            :items="neoReleases"
            density="compact"
            :items-per-page="10"
            class="neo-data-table"
          >
            <template #item.is_active="{ item }">
              <v-chip size="small" :color="item.is_active ? 'success' : 'default'" variant="tonal">
                {{ item.is_active ? "active" : "inactive" }}
              </v-chip>
            </template>
            <template #item.actions="{ item }">
              <div class="d-flex ga-1 flex-wrap">
                <v-btn
                  size="x-small"
                  color="warning"
                  variant="tonal"
                  @click="handleReleaseLifecycleAction(item)"
                >
                  {{ item.is_active ? tm("skills.neoDeactivate") : tm("skills.neoRollback") }}
                </v-btn>
                <v-btn size="x-small" color="primary" variant="tonal" @click="syncRelease(item)">
                  {{ tm("skills.neoSync") }}
                </v-btn>
                <v-btn
                  size="x-small"
                  color="error"
                  variant="tonal"
                  @click="deleteRelease(item)"
                >
                  {{ tm("skills.neoDelete") }}
                </v-btn>
              </div>
            </template>
          </v-data-table>
        </v-card>
      </template>
    </v-container>

    <v-dialog v-model="uploadDialog" max-width="520px">
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6">{{ tm("skills.uploadDialogTitle") }}</v-card-title>
        <v-card-text>
          <small class="text-grey">{{ tm("skills.uploadHint") }}</small>
          <v-file-input
            v-model="uploadFile"
            accept=".zip"
            :label="tm('skills.selectFile')"
            prepend-icon="mdi-folder-zip-outline"
            variant="outlined"
            class="mt-4"
            :multiple="false"
          />
        </v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="uploadDialog = false">{{ tm("skills.cancel") }}</v-btn>
          <v-btn color="primary" :loading="uploading" :disabled="!uploadFile" @click="uploadSkill">
            {{ tm("skills.confirmUpload") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteDialog" max-width="400px">
      <v-card>
        <v-card-title>{{ tm("skills.deleteTitle") }}</v-card-title>
        <v-card-text>{{ tm("skills.deleteMessage") }}</v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="deleteDialog = false">{{ tm("skills.cancel") }}</v-btn>
          <v-btn color="error" :loading="deleting" @click="deleteSkill">
            {{ t("core.common.itemCard.delete") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="payloadDialog.show" max-width="820px">
      <v-card>
        <v-card-title>{{ tm("skills.neoPayloadTitle") }}</v-card-title>
        <v-card-text>
          <pre class="payload-preview">{{ payloadDialog.content }}</pre>
        </v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="payloadDialog.show = false">{{ tm("skills.cancel") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="detailDialog" max-width="1400px">
      <v-card>
        <v-card-title class="dialog-header d-flex justify-space-between align-center pa-3">
          <span class="dialog-title">{{ tm("skills.detailDialogTitle") }}: {{ currentSkill?.name }}</span>
          <v-btn icon="mdi-close" variant="text" density="compact" size="small" @click="detailDialog = false"></v-btn>
        </v-card-title>
        <v-card-text class="pa-0 bg-surface">
          <v-container fluid class="pa-0" style="height: 600px">
            <v-row style="height: 100%">
              <v-col cols="4" class="file-tree-sidebar" style="height: 100%; overflow: auto">
                <div class="file-tree-header">
                  <div class="text-subtitle-2 mb-0 pa-2">{{ tm("skills.detailFilesTitle") }}</div>
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
              <v-col cols="8" class="editor-column" style="height: 100%">
                <div v-if="!currentFile" class="d-flex align-center justify-center h-100 text-disabled">
                  {{ tm("skills.detailNoFileSelected") }}
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
                      style="height: 520px"
                      :options="{ minimap: { enabled: false }, scrollBeyondLastLine: false }"
                    />
                  </div>
                </div>
              </v-col>
            </v-row>
          </v-container>
        </v-card-text>
        <v-card-actions class="dialog-actions d-flex justify-end pa-2">
          <v-btn variant="text" size="small" @click="detailDialog = false">{{ tm("skills.cancel") }}</v-btn>
          <v-btn color="primary" size="small" :loading="saving" :disabled="!currentFile" @click="saveSkillDetail">
            {{ tm("buttons.save") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="hotDialog" max-width="960px">
      <v-card>
        <v-card-title class="text-h4 pa-4 pb-0 pl-6">{{ tm("skills.hotDialogTitle") }}</v-card-title>
        <v-card-text>
          <v-btn-toggle v-model="marketView" mandatory class="mt-4 mb-3" density="comfortable" color="primary">
            <v-btn value="hot">{{ tm("skills.viewHot") }}</v-btn>
            <v-btn value="trending">{{ tm("skills.viewTrending24h") }}</v-btn>
            <v-btn value="all">{{ tm("skills.viewAllTime") }}</v-btn>
          </v-btn-toggle>

          <v-text-field
            v-model="hotSearch"
            :label="tm('skills.hotSearch')"
            clearable
            prepend-inner-icon="mdi-magnify"
            variant="outlined"
            :hint="tm('skills.searchHint')"
            persistent-hint
            class="mt-2"
          />

          <div class="d-flex justify-space-between align-center mb-2">
            <small class="text-grey">
              {{ marketSourceHint }}
            </small>
            <v-btn color="primary" variant="tonal" prepend-icon="mdi-refresh" :loading="hotLoading" @click="fetchHotSkills(true)">
              {{ tm("skills.hotRefresh") }}
            </v-btn>
          </div>

          <v-progress-linear v-if="hotLoading" indeterminate color="primary" class="mb-3" />

          <div v-else-if="!hotSkills || hotSkills.length === 0" class="text-center pa-8">
            <v-icon size="56" color="grey-lighten-1">mdi-fire-off</v-icon>
            <p class="text-grey mt-4">{{ isSearching ? tm("skills.searchEmpty") : tm("skills.hotEmpty") }}</p>
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
                    {{ tm("skills.hotInstalls") }}: {{ skill.installs }}
                    <span v-if="Number.isFinite(Number(skill.change))" class="ms-3"
                      >{{ tm("skills.hotChange") }}: {{ formatChange(skill.change) }}</span
                    >
                  </div>
                </div>
              </template>
              <template #append>
                <v-btn
                  color="primary"
                  size="small"
                  :loading="hotItemLoading[getHotSkillKey(skill)] || false"
                  @click="installHotSkill(skill)"
                >
                  {{ tm("skills.install") }}
                </v-btn>
              </template>
            </v-list-item>
          </v-list>
        </v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="hotDialog = false">{{ tm("skills.cancel") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar v-model="snackbar.show" :timeout="3500" :color="snackbar.color" elevation="24">
      {{ snackbar.message }}
    </v-snackbar>
  </div>
</template>

<script>
import axios from "axios";
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import ItemCard from "@/components/shared/ItemCard.vue";
import { VueMonacoEditor } from "@guolao/vue-monaco-editor";
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
      const ext = fileName.split(".").pop().toLowerCase();
      const iconMap = {
        md: "mdi-language-markdown",
        py: "mdi-language-python",
        js: "mdi-language-javascript",
        ts: "mdi-language-typescript",
        json: "mdi-code-json",
        yaml: "mdi-yaml",
        yml: "mdi-yaml",
        xml: "mdi-xml",
        html: "mdi-language-html5",
        css: "mdi-language-css3",
        txt: "mdi-text",
        sh: "mdi-console",
        bash: "mdi-console",
      };
      return iconMap[ext] || "mdi-file-document-outline";
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

    const mode = ref("local");
    const skills = ref([]);
    const loading = ref(false);
    const runtime = ref("local");
    const sandboxCache = reactive({ ready: false, count: 0, updated_at: null });

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

    const neoLoading = ref(false);
    const neoCandidates = ref([]);
    const neoReleases = ref([]);
    const neoFilters = reactive({
      skill_key: "",
      status: "",
      stage: "",
    });
    const candidatePromoteLoading = reactive({});
    const payloadDialog = reactive({
      show: false,
      content: "",
    });

    const neoEnabled = ref(false);
    const neoUnavailableMessage = ref("");

    const candidateStatusItems = computed(() => [
      { title: tm("skills.neoAll"), value: "" },
      { title: "draft", value: "draft" },
      { title: "evaluating", value: "evaluating" },
      { title: "promoted", value: "promoted" },
      { title: "promoted_canary", value: "promoted_canary" },
      { title: "promoted_stable", value: "promoted_stable" },
      { title: "rejected", value: "rejected" },
      { title: "rolled_back", value: "rolled_back" },
    ]);

    const releaseStageItems = computed(() => [
      { title: tm("skills.neoAll"), value: "" },
      { title: "canary", value: "canary" },
      { title: "stable", value: "stable" },
    ]);

    const activeReleaseCount = computed(() =>
      neoReleases.value.filter((item) => item?.is_active).length
    );

    const candidateHeaders = computed(() => [
      { title: "ID", key: "id", width: "180px" },
      { title: "skill_key", key: "skill_key" },
      { title: "status", key: "status", width: "130px" },
      { title: "score", key: "latest_score", width: "90px" },
      { title: tm("skills.actions"), key: "actions", sortable: false, width: "420px" },
    ]);

    const releaseHeaders = computed(() => [
      { title: "ID", key: "id", width: "180px" },
      { title: "skill_key", key: "skill_key" },
      { title: "stage", key: "stage", width: "100px" },
      { title: "version", key: "version", width: "90px" },
      { title: "active", key: "is_active", width: "110px" },
      { title: tm("skills.actions"), key: "actions", sortable: false, width: "220px" },
    ]);

    const showMessage = (message, color = "success") => {
      snackbar.message = message;
      snackbar.color = color;
      snackbar.show = true;
    };

    const normalizeSkillsPayload = (res) => {
      const payload = res?.data?.data || [];
      if (Array.isArray(payload)) {
        runtime.value = "local";
        sandboxCache.ready = false;
        sandboxCache.count = 0;
        sandboxCache.updated_at = null;
        return payload;
      }
      runtime.value = payload.runtime || "local";
      const cache = payload.sandbox_cache || {};
      sandboxCache.ready = !!cache.ready;
      sandboxCache.count = Number(cache.count || 0);
      sandboxCache.updated_at = cache.updated_at || null;
      return payload.skills || [];
    };

    const sourceTypeLabel = (sourceType) => {
      if (sourceType === "sandbox_only") return tm("skills.sourceSandboxOnly");
      if (sourceType === "both") return tm("skills.sourceBoth");
      return tm("skills.sourceLocalOnly");
    };

    const sourceTypeColor = (sourceType) => {
      if (sourceType === "sandbox_only") return "indigo";
      if (sourceType === "both") return "success";
      return "primary";
    };

    const isSandboxPresetSkill = (skill) => skill?.source_type === "sandbox_only";

    const normalizeNeoItemsPayload = (res) => {
      const payload = res?.data?.data || [];
      if (Array.isArray(payload)) return payload;
      if (Array.isArray(payload.items)) return payload.items;
      return [];
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
        skills.value = normalizeSkillsPayload(res);
      } catch (_err) {
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
        const payload = res?.data?.data || {};
        if (Array.isArray(payload)) {
          hotSkills.value = payload;
        } else {
          hotSkills.value = payload.skills || [];
        }
      } catch (_err) {
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
      } catch (_err) {
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
        const file = Array.isArray(uploadFile.value) ? uploadFile.value[0] : uploadFile.value;
        if (!file) {
          uploading.value = false;
          return;
        }
        formData.append("file", file);
        const res = await axios.post("/api/skills/upload", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        handleApiResponse(res, tm("skills.uploadSuccess"), tm("skills.uploadFailed"), async () => {
          uploadDialog.value = false;
          uploadFile.value = null;
          await fetchSkills();
        });
      } catch (_err) {
        showMessage(tm("skills.uploadFailed"), "error");
      } finally {
        uploading.value = false;
      }
    };

    const toggleSkill = async (skill) => {
      if (isSandboxPresetSkill(skill)) {
        showMessage(tm("skills.sandboxPresetReadonly"), "warning");
        return;
      }
      const nextActive = !skill.active;
      itemLoading[skill.name] = true;
      try {
        const res = await axios.post("/api/skills/update", {
          name: skill.name,
          active: nextActive,
        });
        handleApiResponse(res, tm("skills.updateSuccess"), tm("skills.updateFailed"), () => {
          skill.active = nextActive;
        });
      } catch (_err) {
        showMessage(tm("skills.updateFailed"), "error");
      } finally {
        itemLoading[skill.name] = false;
      }
    };

    const confirmDelete = (skill) => {
      if (isSandboxPresetSkill(skill)) {
        showMessage(tm("skills.sandboxPresetReadonly"), "warning");
        return;
      }
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
        handleApiResponse(res, tm("skills.deleteSuccess"), tm("skills.deleteFailed"), async () => {
          deleteDialog.value = false;
          await fetchSkills();
        });
      } catch (_err) {
        showMessage(tm("skills.deleteFailed"), "error");
      } finally {
        deleting.value = false;
      }
    };

    const downloadSkill = async (skill) => {
      if (isSandboxPresetSkill(skill)) {
        showMessage(tm("skills.sandboxPresetReadonly"), "warning");
        return;
      }
      itemLoading[skill.name] = true;
      try {
        const res = await axios.get("/api/skills/download", {
          params: { name: skill.name },
          responseType: "blob",
        });
        const blob = new Blob([res.data], { type: "application/zip" });
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${skill.name}.zip`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
        showMessage(tm("skills.downloadSuccess"), "success");
      } catch (_err) {
        showMessage(tm("skills.downloadFailed"), "error");
      } finally {
        itemLoading[skill.name] = false;
      }
    };

    const fetchNeoCandidates = async () => {
      const params = {
        skill_key: neoFilters.skill_key || undefined,
        status: neoFilters.status || undefined,
      };
      const res = await axios.get("/api/skills/neo/candidates", { params });
      neoCandidates.value = normalizeNeoItemsPayload(res);
    };

    const fetchNeoReleases = async () => {
      const params = {
        skill_key: neoFilters.skill_key || undefined,
        stage: neoFilters.stage || undefined,
      };
      const res = await axios.get("/api/skills/neo/releases", { params });
      neoReleases.value = normalizeNeoItemsPayload(res).map((item) => {
        if (!item || typeof item !== "object") {
          return item;
        }
        return {
          ...item,
          is_active: item.is_active ?? item.active ?? false,
        };
      });
    };

    const loadNeoAvailability = async () => {
      try {
        const res = await axios.get("/api/config/get");
        const config = res?.data?.data?.config || {};
        const providerSettings = config?.provider_settings || {};
        const runtimeValue = providerSettings?.computer_use_runtime || "local";
        const booter = providerSettings?.sandbox?.booter || "";
        neoEnabled.value = runtimeValue === "sandbox" && booter === "shipyard_neo";
      } catch (_err) {
        neoEnabled.value = false;
      }

      neoUnavailableMessage.value = tm("skills.neoRuntimeRequired");
      if (!neoEnabled.value && mode.value === "neo") {
        mode.value = "local";
      }
    };

    const fetchNeoData = async () => {
      neoLoading.value = true;
      try {
        await Promise.all([fetchNeoCandidates(), fetchNeoReleases()]);
      } catch (_err) {
        showMessage(tm("skills.neoLoadFailed"), "error");
      } finally {
        neoLoading.value = false;
      }
    };

    const evaluateCandidate = async (candidate, passed) => {
      try {
        const res = await axios.post("/api/skills/neo/evaluate", {
          candidate_id: candidate.id,
          passed,
          score: passed ? 1.0 : 0.0,
          report: passed ? "approved_from_webui" : "rejected_from_webui",
        });
        handleApiResponse(res, tm("skills.neoEvaluateSuccess"), tm("skills.neoEvaluateFailed"), async () => {
          await fetchNeoCandidates();
        });
      } catch (_err) {
        showMessage(tm("skills.neoEvaluateFailed"), "error");
      }
    };

    const candidatePromoteLoadingKey = (candidateId, stage) => `${candidateId}:${stage}`;
    const isCandidatePromoteLoading = (candidateId, stage) =>
      !!candidatePromoteLoading[candidatePromoteLoadingKey(candidateId, stage)];
    const isCandidatePromoting = (candidateId) =>
      isCandidatePromoteLoading(candidateId, "canary") || isCandidatePromoteLoading(candidateId, "stable");

    const promoteCandidate = async (candidate, stage) => {
      const candidateId = candidate?.id;
      if (!candidateId) return;
      const loadingKey = candidatePromoteLoadingKey(candidateId, stage);
      if (candidatePromoteLoading[loadingKey]) return;
      candidatePromoteLoading[loadingKey] = true;
      try {
        const res = await axios.post("/api/skills/neo/promote", {
          candidate_id: candidateId,
          stage,
          sync_to_local: true,
        });
        const ok = res?.data?.status === "ok";
        if (!ok) {
          showMessage(res?.data?.message || tm("skills.neoPromoteFailed"), "error");
        } else {
          showMessage(tm("skills.neoPromoteSuccess"), "success");
        }
        await fetchNeoData();
        if (stage === "stable") {
          await fetchSkills();
        }
      } catch (_err) {
        showMessage(tm("skills.neoPromoteFailed"), "error");
      } finally {
        candidatePromoteLoading[loadingKey] = false;
      }
    };

    const rollbackRelease = async (release) => {
      try {
        const res = await axios.post("/api/skills/neo/rollback", {
          release_id: release.id,
        });
        handleApiResponse(res, tm("skills.neoRollbackSuccess"), tm("skills.neoRollbackFailed"), async () => {
          await fetchNeoData();
        });
      } catch (_err) {
        showMessage(tm("skills.neoRollbackFailed"), "error");
      }
    };

    const deactivateRelease = async (release) => {
      try {
        const res = await axios.post("/api/skills/neo/rollback", {
          release_id: release.id,
        });
        handleApiResponse(
          res,
          tm("skills.neoDeactivateSuccess"),
          tm("skills.neoDeactivateFailed"),
          async () => {
            await fetchNeoData();
          }
        );
      } catch (_err) {
        showMessage(tm("skills.neoDeactivateFailed"), "error");
      }
    };

    const handleReleaseLifecycleAction = async (release) => {
      if (release?.is_active) {
        await deactivateRelease(release);
        return;
      }
      await rollbackRelease(release);
    };

    const syncRelease = async (release) => {
      try {
        const res = await axios.post("/api/skills/neo/sync", {
          release_id: release.id,
        });
        handleApiResponse(res, tm("skills.neoSyncSuccess"), tm("skills.neoSyncFailed"), async () => {
          await fetchSkills();
        });
      } catch (_err) {
        showMessage(tm("skills.neoSyncFailed"), "error");
      }
    };

    const viewPayload = async (payloadRef) => {
      if (!payloadRef) return;
      try {
        const res = await axios.get("/api/skills/neo/payload", {
          params: { payload_ref: payloadRef },
        });
        if (res?.data?.status !== "ok") {
          showMessage(res?.data?.message || tm("skills.neoPayloadFailed"), "error");
          return;
        }
        const payload = res?.data?.data || {};
        payloadDialog.content = JSON.stringify(payload, null, 2);
        payloadDialog.show = true;
      } catch (_err) {
        showMessage(tm("skills.neoPayloadFailed"), "error");
      }
    };

    const deleteCandidate = async (candidate) => {
      try {
        const res = await axios.post("/api/skills/neo/delete-candidate", {
          candidate_id: candidate.id,
          reason: "deleted_from_webui",
        });
        handleApiResponse(res, tm("skills.neoDeleteSuccess"), tm("skills.neoDeleteFailed"), async () => {
          await fetchNeoData();
        });
      } catch (_err) {
        showMessage(tm("skills.neoDeleteFailed"), "error");
      }
    };

    const deleteRelease = async (release) => {
      try {
        const res = await axios.post("/api/skills/neo/delete-release", {
          release_id: release.id,
          reason: "deleted_from_webui",
        });
        handleApiResponse(res, tm("skills.neoDeleteSuccess"), tm("skills.neoDeleteFailed"), async () => {
          await fetchNeoData();
        });
      } catch (_err) {
        showMessage(tm("skills.neoDeleteFailed"), "error");
      }
    };

    const openDetailDialog = async (skill) => {
      if (isSandboxPresetSkill(skill)) {
        showMessage(tm("skills.sandboxPresetReadonly"), "warning");
        return;
      }
      currentSkill.value = skill;
      fileTree.value = [];
      currentFile.value = null;
      skillContent.value = "";
      detailDialog.value = true;
      try {
        const res = await axios.get("/api/skills/detail", {
          params: { name: skill.name },
        });
        if (res?.data?.status !== "ok") {
          showMessage(res?.data?.message || tm("skills.loadDetailFailed"), "error");
          return;
        }
        fileTree.value = res?.data?.data?.files || [];

        const findSkillMd = (items) => {
          for (const item of items) {
            if (item.type === "file" && item.name === "SKILL.md") {
              return item.path;
            }
            if (item.type === "directory" && item.children) {
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
      } catch (_err) {
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
      if (file && file.type === "file") {
        await loadFileContent(path);
      }
    };

    const loadFileContent = async (filePath) => {
      if (!currentSkill.value) return;
      try {
        const res = await axios.get("/api/skills/file", {
          params: {
            name: currentSkill.value.name,
            file: filePath,
          },
        });
        if (res?.data?.status === "ok") {
          currentFile.value = filePath;
          skillContent.value = res?.data?.data?.content || "";
        } else {
          showMessage(res?.data?.message || tm("skills.loadFileFailed"), "error");
        }
      } catch (_err) {
        showMessage(tm("skills.loadFileFailed"), "error");
      }
    };

    const getFileLanguage = (fileName) => {
      const ext = String(fileName || "").split(".").pop().toLowerCase();
      const langMap = {
        md: "markdown",
        py: "python",
        js: "javascript",
        ts: "typescript",
        json: "json",
        yaml: "yaml",
        yml: "yaml",
        xml: "xml",
        html: "html",
        css: "css",
        txt: "plaintext",
      };
      return langMap[ext] || "plaintext";
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
        handleApiResponse(res, tm("skills.saveDetailSuccess"), tm("skills.saveDetailFailed"), async () => {
          await fetchSkills();
        });
      } catch (_err) {
        showMessage(tm("skills.saveDetailFailed"), "error");
      } finally {
        saving.value = false;
      }
    };

    const refreshCurrentMode = async () => {
      if (mode.value === "neo") {
        await loadNeoAvailability();
        if (neoEnabled.value) {
          await fetchNeoData();
        } else {
          showMessage(tm("skills.neoRuntimeRequired"), "warning");
        }
      } else {
        await fetchSkills();
      }
    };

    watch(mode, async (nextMode) => {
      if (nextMode === "neo") {
        await loadNeoAvailability();
        if (neoEnabled.value) {
          await fetchNeoData();
        }
      } else {
        await fetchSkills();
      }
    });

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

    onMounted(async () => {
      await Promise.all([fetchSkills(), loadNeoAvailability()]);
      if (neoEnabled.value) {
        await fetchNeoData();
      }
    });

    return {
      t,
      tm,
      mode,
      skills,
      loading,
      runtime,
      sandboxCache,
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
      neoEnabled,
      neoUnavailableMessage,
      neoLoading,
      neoCandidates,
      neoReleases,
      neoFilters,
      candidateStatusItems,
      releaseStageItems,
      activeReleaseCount,
      candidateHeaders,
      releaseHeaders,
      payloadDialog,
      refreshCurrentMode,
      fetchNeoData,
      getHotSkillKey,
      formatChange,
      fetchHotSkills,
      openHotDialog,
      installHotSkill,
      fetchSkills,
      uploadSkill,
      downloadSkill,
      toggleSkill,
      confirmDelete,
      deleteSkill,
      evaluateCandidate,
      promoteCandidate,
      isCandidatePromoteLoading,
      isCandidatePromoting,
      rollbackRelease,
      deactivateRelease,
      handleReleaseLifecycleAction,
      syncRelease,
      viewPayload,
      deleteCandidate,
      deleteRelease,
      sourceTypeLabel,
      sourceTypeColor,
      isSandboxPresetSkill,
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
  min-height: 20px;
}

.skill-path {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
  word-break: break-all;
}

.payload-preview {
  max-height: 480px;
  overflow: auto;
  background: #111;
  color: #ececec;
  padding: 12px;
  border-radius: 8px;
  font-size: 12px;
}

.neo-filter-card {
  border-radius: 14px;
  border-color: rgba(var(--v-theme-primary), 0.25);
  background: linear-gradient(180deg, rgba(var(--v-theme-primary), 0.03), rgba(var(--v-theme-surface), 1));
}

.neo-table-card {
  border-radius: 14px;
}

.neo-data-table :deep(.v-data-table-header__content) {
  font-weight: 700;
}

.neo-data-table :deep(tbody tr:hover) {
  background: rgba(var(--v-theme-primary), 0.04);
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
