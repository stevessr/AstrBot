<template>
  <div class="skills-page">
    <v-container fluid class="pa-0" elevation="0">
      <v-row
        v-if="neoEnabled"
        class="d-flex justify-end align-center px-4 py-3 pb-4"
      >
        <v-btn-toggle v-model="mode" mandatory divided density="comfortable">
          <v-btn value="local">{{ tm("skills.modeLocal") }}</v-btn>
          <v-btn value="neo">{{ tm("skills.modeNeo") }}</v-btn>
        </v-btn-toggle>
      </v-row>

      <div v-if="mode === 'local'" class="px-2 pb-2 d-flex flex-column ga-2">
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
        <v-alert
          type="warning"
          variant="tonal"
          density="comfortable"
          border="start"
        >
          {{ neoUnavailableMessage }}
        </v-alert>
      </div>

      <template v-if="mode === 'local'">
        <v-progress-linear
          v-if="loading"
          indeterminate
          color="primary"
        ></v-progress-linear>

        <div v-else-if="skills.length === 0" class="text-center pa-8">
          <v-icon size="64" color="grey-lighten-1">mdi-folder-open</v-icon>
          <p class="text-grey mt-4">{{ tm("skills.empty") }}</p>
          <small class="text-grey">{{ tm("skills.emptyHint") }}</small>
        </div>

        <div v-else class="pb-3">
          <h3 class="skills-list-title text-h3">
            {{ tm("status.installed") }}
          </h3>

          <div class="skills-list">
            <OutlinedActionListItem
              v-for="skill in skills"
              :key="skill.name"
              :title="skill.name"
              class="skill-list-item"
              :class="{
                'skill-list-item--inactive':
                  skill.active === false || isInactivePluginSkill(skill),
              }"
              clickable
              @click="openSkillEditor(skill)"
            >
              <template #title-extra>
                <div class="d-flex align-center ga-1">
                  <v-chip
                    v-if="skill.preset || skill.source_type === 'sandbox_only'"
                    size="x-small"
                    variant="tonal"
                    color="secondary"
                  >
                    {{ tm("status.preset") }}
                  </v-chip>
                  <v-chip
                    v-if="isInactivePluginSkill(skill)"
                    size="x-small"
                    variant="tonal"
                    color="warning"
                  >
                    {{ tm("skills.pluginDisabled") }}
                  </v-chip>
                </div>
              </template>

              <div class="skill-description text-body-2 text-medium-emphasis">
                {{ skill.description || tm("skills.noDescription") }}
              </div>

              <div class="skill-path text-caption text-medium-emphasis">
                <v-icon size="small" class="me-1">mdi-file-document</v-icon>
                {{ tm("skills.path") }}: {{ skill.path }}
              </div>

              <template #actions>
                <v-tooltip :text="tm('skills.download')" location="top">
                  <template #activator="{ props }">
                    <v-btn
                      v-bind="props"
                      icon="mdi-download-outline"
                      variant="text"
                      size="small"
                      class="list-action-icon-btn"
                      :disabled="
                        itemLoading[skill.name] || isReadOnlySourceSkill(skill)
                      "
                      @click.stop="downloadSkill(skill)"
                    />
                  </template>
                </v-tooltip>

                <v-tooltip
                  :text="t('core.common.itemCard.delete')"
                  location="top"
                >
                  <template #activator="{ props }">
                    <v-btn
                      v-bind="props"
                      icon="mdi-delete-outline"
                      variant="text"
                      size="small"
                      class="list-action-icon-btn"
                      :disabled="
                        itemLoading[skill.name] || isReadOnlySourceSkill(skill)
                      "
                      @click.stop="confirmDelete(skill)"
                    />
                  </template>
                </v-tooltip>
              </template>

              <template #control>
                <v-tooltip location="top">
                  <template #activator="{ props }">
                    <v-switch
                      v-bind="props"
                      color="primary"
                      density="compact"
                      hide-details
                      inset
                      :model-value="
                        skill.active && !isInactivePluginSkill(skill)
                      "
                      :aria-label="
                        isInactivePluginSkill(skill)
                          ? tm('skills.pluginDisabled')
                          : skill.active
                          ? tm('skills.disable')
                          : tm('skills.enable')
                      "
                      :loading="itemLoading[skill.name] || false"
                      :disabled="
                        itemLoading[skill.name] ||
                        isSandboxPresetSkill(skill) ||
                        isInactivePluginSkill(skill)
                      "
                      @click.stop
                      @update:model-value="toggleSkill(skill)"
                    />
                  </template>
                  <span>{{
                    isInactivePluginSkill(skill)
                      ? tm("skills.pluginDisabled")
                      : skill.active
                      ? tm("skills.disable")
                      : tm("skills.enable")
                  }}</span>
                </v-tooltip>
              </template>
            </OutlinedActionListItem>
          </div>
        </div>
      </template>

      <template v-else-if="mode === 'neo' && neoEnabled">
        <v-card class="mx-3 mb-4 pa-4 neo-filter-card" variant="outlined">
          <div
            class="d-flex flex-wrap justify-space-between align-center ga-2 mb-3"
          >
            <div>
              <div class="text-subtitle-1 font-weight-bold">Neo Skills</div>
              <div class="text-caption text-medium-emphasis">
                {{ tm("skills.neoFilterHint") }}
              </div>
            </div>
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

        <v-progress-linear
          v-if="neoLoading"
          indeterminate
          color="primary"
        ></v-progress-linear>

        <div class="mx-3 mb-3 d-flex flex-wrap ga-2">
          <v-chip size="small" color="primary" variant="tonal"
            >Candidates: {{ neoCandidates.length }}</v-chip
          >
          <v-chip size="small" color="indigo" variant="tonal"
            >Releases: {{ neoReleases.length }}</v-chip
          >
          <v-chip size="small" color="success" variant="tonal"
            >Active: {{ activeReleaseCount }}</v-chip
          >
        </div>

        <v-card class="mx-3 mb-4 neo-table-card" variant="outlined">
          <v-card-title class="text-subtitle-1 font-weight-bold">{{
            tm("skills.neoCandidates")
          }}</v-card-title>
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
                <v-btn
                  size="x-small"
                  color="success"
                  variant="tonal"
                  @click="evaluateCandidate(item, true)"
                >
                  {{ tm("skills.neoPass") }}
                </v-btn>
                <v-btn
                  size="x-small"
                  color="warning"
                  variant="tonal"
                  @click="evaluateCandidate(item, false)"
                >
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
                  :disabled="!item.payload_ref"
                  @click="viewPayload(item.payload_ref)"
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
          <v-card-title class="text-subtitle-1 font-weight-bold">{{
            tm("skills.neoReleases")
          }}</v-card-title>
          <v-data-table
            :headers="releaseHeaders"
            :items="neoReleases"
            density="compact"
            :items-per-page="10"
            class="neo-data-table"
          >
            <template #item.is_active="{ item }">
              <v-chip
                size="small"
                :color="item.is_active ? 'success' : 'default'"
                variant="tonal"
              >
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
                  {{
                    item.is_active
                      ? tm("skills.neoDeactivate")
                      : tm("skills.neoRollback")
                  }}
                </v-btn>
                <v-btn
                  size="x-small"
                  color="primary"
                  variant="tonal"
                  @click="syncRelease(item)"
                >
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

    <div class="skills-fab-stack">
      <v-tooltip :text="tm('skills.refresh')" location="left">
        <template #activator="{ props }">
          <v-btn
            v-bind="props"
            color="darkprimary"
            icon="mdi-refresh"
            size="x-large"
            variant="elevated"
            class="skills-fab"
            @click="refreshCurrentMode"
          />
        </template>
      </v-tooltip>
      <v-tooltip
        v-if="mode === 'local'"
        :text="tm('skills.upload')"
        location="left"
      >
        <template #activator="{ props }">
          <v-btn
            v-bind="props"
            color="darkprimary"
            icon="mdi-upload"
            size="x-large"
            variant="elevated"
            class="skills-fab"
            @click="openUploadDialog"
          />
        </template>
      </v-tooltip>
      <v-tooltip
        v-if="mode === 'local'"
        :text="tm('skills.installFromSource')"
        location="left"
      >
        <template #activator="{ props }">
          <v-btn
            v-bind="props"
            color="darkprimary"
            icon="mdi-cloud-download-outline"
            size="x-large"
            variant="elevated"
            class="skills-fab"
            @click="openImportDialog"
          />
        </template>
      </v-tooltip>
    </div>

    <v-dialog v-model="uploadDialog" max-width="880px" :persistent="uploading">
      <v-card class="skills-upload-dialog">
        <v-card-title
          class="text-h3 pa-4 pb-0 pl-6 skills-upload-dialog__header"
        >
          <div class="skills-upload-dialog__heading">
            <div>
              {{ tm("skills.uploadDialogTitle") }}
            </div>
          </div>
          <v-btn
            class="skills-upload-dialog__close"
            icon="mdi-close"
            variant="text"
            :disabled="uploading"
            @click="closeUploadDialog"
          />
        </v-card-title>

        <v-card-text class="skills-upload-dialog__body px-6 pb-5 pt-2">
          <p
            class="skills-upload-dialog__description skills-upload-dialog__description--body"
          >
            {{ tm("skills.uploadHint") }}
          </p>

          <div class="skills-upload-structure-note">
            <v-icon size="18">mdi-information-outline</v-icon>
            <span>{{ tm("skills.structureRequirement") }}</span>
          </div>

          <div class="skills-upload-capabilities">
            <div class="skills-upload-capability">
              <div class="skills-upload-capability__icon">
                <v-icon size="18">mdi-layers-outline</v-icon>
              </div>
              <span>{{ tm("skills.abilityMultiple") }}</span>
            </div>
            <div class="skills-upload-capability">
              <div class="skills-upload-capability__icon">
                <v-icon size="18">mdi-shield-check-outline</v-icon>
              </div>
              <span>{{ tm("skills.abilityValidate") }}</span>
            </div>
            <div class="skills-upload-capability">
              <div class="skills-upload-capability__icon">
                <v-icon size="18">mdi-skip-next-circle-outline</v-icon>
              </div>
              <span>{{ tm("skills.abilitySkip") }}</span>
            </div>
          </div>

          <div
            class="skills-dropzone"
            :class="{ 'skills-dropzone--dragover': isUploadDragging }"
            role="button"
            tabindex="0"
            :aria-label="tm('skills.dropzoneTitle')"
            @click="openUploadPicker"
            @keydown.enter="openUploadPicker"
            @keydown.space.prevent="openUploadPicker"
            @dragover.prevent="isUploadDragging = true"
            @dragleave.prevent="isUploadDragging = false"
            @drop.prevent="handleUploadDrop"
          >
            <div class="skills-dropzone__icon">
              <v-icon size="34">mdi-folder-zip-outline</v-icon>
            </div>
            <div class="text-h6 font-weight-medium">
              {{ tm("skills.dropzoneTitle") }}
            </div>
            <div class="skills-dropzone__subtitle">
              {{ tm("skills.dropzoneAction") }}
            </div>
            <div class="skills-dropzone__hint">
              {{ tm("skills.dropzoneHint") }}
            </div>
            <input
              ref="uploadInput"
              type="file"
              multiple
              hidden
              accept=".zip"
              @change="handleUploadSelection"
            />
          </div>

          <div v-if="uploadItems.length > 0" class="skills-upload-summary">
            <v-chip
              size="small"
              variant="flat"
              class="skills-upload-summary__chip"
            >
              {{
                tm("skills.summaryTotal", { count: uploadStateCounts.total })
              }}
            </v-chip>
            <v-chip
              size="small"
              variant="flat"
              class="skills-upload-summary__chip"
            >
              {{
                tm("skills.summaryReady", {
                  count:
                    uploadStateCounts.waiting + uploadStateCounts.uploading,
                })
              }}
            </v-chip>
            <v-chip
              size="small"
              variant="flat"
              class="skills-upload-summary__chip skills-upload-summary__chip--success"
            >
              {{
                tm("skills.summarySuccess", {
                  count: uploadStateCounts.success,
                })
              }}
            </v-chip>
            <v-chip
              size="small"
              variant="flat"
              class="skills-upload-summary__chip skills-upload-summary__chip--error"
            >
              {{
                tm("skills.summaryFailed", { count: uploadStateCounts.error })
              }}
            </v-chip>
            <v-chip
              size="small"
              variant="flat"
              class="skills-upload-summary__chip"
            >
              {{
                tm("skills.summarySkipped", {
                  count: uploadStateCounts.skipped,
                })
              }}
            </v-chip>
          </div>

          <div v-if="uploadItems.length > 0" class="skills-upload-list">
            <div class="skills-upload-list__header">
              <span>{{ tm("skills.fileListTitle") }}</span>
            </div>
            <div
              v-for="item in uploadItems"
              :key="item.id"
              class="skills-upload-row"
            >
              <div class="skills-upload-row__meta">
                <div class="skills-upload-row__name">{{ item.name }}</div>
                <div class="skills-upload-row__size">
                  {{ formatFileSize(item.size) }}
                </div>
                <div class="skills-upload-row__message">
                  {{ item.validationMessage }}
                </div>
              </div>
              <div class="skills-upload-row__actions">
                <v-chip
                  size="small"
                  variant="flat"
                  :class="statusChipClass(item.status)"
                >
                  {{ uploadStatusLabel(item.status) }}
                </v-chip>
                <v-btn
                  icon="mdi-close"
                  size="small"
                  variant="text"
                  :disabled="uploading || item.status === 'uploading'"
                  @click="removeUploadItem(item.id)"
                />
              </div>
            </div>
          </div>
          <div v-else class="skills-upload-empty">
            {{ tm("skills.fileListEmpty") }}
          </div>
        </v-card-text>

        <v-card-actions
          class="skills-upload-dialog__actions justify-end px-6 pb-3 pt-2"
        >
          <v-btn
            class="skills-upload-dialog__action-btn"
            variant="tonal"
            color="secondary"
            :disabled="uploading"
            @click="closeUploadDialog"
          >
            {{ tm("skills.cancel") }}
          </v-btn>
          <v-btn
            class="skills-upload-dialog__action-btn"
            variant="tonal"
            color="primary"
            :loading="uploading"
            :disabled="!hasUploadableItems"
            @click="uploadSkillBatch"
          >
            {{ tm("skills.confirmUpload") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteDialog" max-width="400px">
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6">{{
          tm("skills.deleteTitle")
        }}</v-card-title>
        <v-card-text>{{ tm("skills.deleteMessage") }}</v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="deleteDialog = false">{{
            tm("skills.cancel")
          }}</v-btn>
          <v-btn
            color="error"
            variant="tonal"
            :loading="deleting"
            @click="deleteSkill"
          >
            {{ t("core.common.itemCard.delete") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog
      v-model="editorDialog.show"
      max-width="1180px"
      :persistent="editorDialog.saving"
    >
      <v-card class="skill-editor-dialog">
        <v-card-title
          class="text-h3 pa-4 pb-0 pl-6 skill-editor-dialog__header"
        >
          <div>
            <div>
              {{ editorDialog.skillName }}
            </div>
          </div>
          <v-btn
            icon="mdi-close"
            variant="text"
            :disabled="editorDialog.saving"
            @click="closeSkillEditor"
          />
        </v-card-title>

        <v-card-text class="skill-editor-dialog__body">
          <div class="skill-editor">
            <div class="skill-editor__files">
              <div class="skill-editor__files-header">
                <v-btn
                  icon="mdi-arrow-up"
                  size="small"
                  variant="text"
                  :disabled="
                    !editorDialog.currentDir || editorDialog.loadingFiles
                  "
                  @click="openParentSkillDir"
                />
                <span>{{ editorDialog.currentDir || "/" }}</span>
              </div>

              <v-progress-linear
                v-if="editorDialog.loadingFiles"
                indeterminate
                color="primary"
              />

              <div v-else class="skill-editor__file-list">
                <button
                  v-for="entry in editorDialog.entries"
                  :key="`${entry.type}:${entry.path}`"
                  class="skill-editor__file-row"
                  :class="{
                    'skill-editor__file-row--active':
                      editorDialog.filePath === entry.path,
                  }"
                  type="button"
                  @click="openSkillEntry(entry)"
                >
                  <v-icon size="18">
                    {{
                      entry.type === "directory"
                        ? "mdi-folder-outline"
                        : "mdi-file-document-outline"
                    }}
                  </v-icon>
                  <span>{{ entry.name }}</span>
                  <v-chip
                    v-if="entry.type === 'file' && !entry.editable"
                    size="x-small"
                    variant="tonal"
                  >
                    {{ tm("skills.readonly") }}
                  </v-chip>
                </button>
              </div>
            </div>

            <div class="skill-editor__content">
              <div class="skill-editor__content-header">
                <div class="skill-editor__path">
                  {{ editorDialog.filePath || tm("skills.noFileSelected") }}
                </div>
                <v-chip
                  v-if="editorDialog.fileDirty"
                  size="small"
                  color="warning"
                  variant="tonal"
                >
                  {{ tm("skills.unsaved") }}
                </v-chip>
              </div>

              <v-alert
                v-if="editorDialog.error"
                type="error"
                variant="tonal"
                density="compact"
                class="mb-3"
              >
                {{ editorDialog.error }}
              </v-alert>

              <div class="skill-editor__monaco">
                <VueMonacoEditor
                  v-model:value="editorDialog.content"
                  :theme="editorTheme"
                  :language="editorLanguage"
                  :options="editorOptions"
                  style="height: 100%; width: 100%"
                  @change="editorDialog.fileDirty = true"
                />
              </div>
            </div>
          </div>
        </v-card-text>

        <v-card-actions class="skill-editor-dialog__actions">
          <v-spacer />
          <v-btn
            variant="text"
            :disabled="editorDialog.saving"
            @click="closeSkillEditor"
          >
            {{ tm("skills.cancel") }}
          </v-btn>
          <v-btn
            color="primary"
            variant="tonal"
            :loading="editorDialog.saving"
            :disabled="
              !editorDialog.filePath ||
              !editorDialog.fileEditable ||
              !editorDialog.fileDirty
            "
            @click="saveSkillFile"
          >
            {{ tm("skills.saveFile") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="payloadDialog.show" max-width="820px">
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6">{{
          tm("skills.neoPayloadTitle")
        }}</v-card-title>
        <v-card-text>
          <pre class="payload-preview">{{ payloadDialog.content }}</pre>
        </v-card-text>
        <v-card-actions class="d-flex justify-end">
          <v-btn variant="text" @click="payloadDialog.show = false">{{
            tm("skills.cancel")
          }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="importDialog" max-width="960px">
      <v-card class="skills-import-dialog">
        <v-card-title class="px-6 pt-6 pb-2">
          <div class="text-h4 font-weight-medium">
            {{ tm("skills.importDialogTitle") }}
          </div>
        </v-card-title>
        <v-card-text class="px-6 pb-5 pt-2">
          <v-tabs v-model="importMode" color="primary" density="comfortable">
            <v-tab value="skillsSh">{{
              tm("skills.importModeSkillsSh")
            }}</v-tab>
            <v-tab value="github">{{ tm("skills.importModeGitHub") }}</v-tab>
          </v-tabs>

          <v-window v-model="importMode" class="mt-4">
            <v-window-item value="skillsSh">
              <div class="d-flex flex-column flex-md-row ga-3 mb-3">
                <v-text-field
                  v-model="skillsShQuery"
                  :label="tm('skills.skillsShSourceLabel')"
                  prepend-inner-icon="mdi-store-search-outline"
                  variant="outlined"
                  :hint="tm('skills.skillsShSourceHint')"
                  persistent-hint
                  hide-details="auto"
                  class="flex-grow-1"
                  @keydown.enter="scanSkillsSh"
                />
                <v-btn
                  color="primary"
                  variant="tonal"
                  prepend-icon="mdi-magnify-scan"
                  :loading="importScanLoading"
                  @click="scanSkillsSh"
                >
                  {{ tm("skills.skillsShScan") }}
                </v-btn>
              </div>
            </v-window-item>

            <v-window-item value="github">
              <div class="d-flex flex-column flex-md-row ga-3 mb-3">
                <v-text-field
                  v-model="repoInput"
                  :label="tm('skills.githubRepoLabel')"
                  prepend-inner-icon="mdi-github"
                  variant="outlined"
                  :hint="tm('skills.githubRepoHint')"
                  persistent-hint
                  hide-details="auto"
                  class="flex-grow-1"
                  @keydown.enter="scanGitHubRepo"
                />
                <v-btn
                  color="primary"
                  variant="tonal"
                  prepend-icon="mdi-magnify-scan"
                  :loading="importScanLoading"
                  @click="scanGitHubRepo"
                >
                  {{ tm("skills.githubScan") }}
                </v-btn>
              </div>
            </v-window-item>
          </v-window>

          <v-progress-linear
            v-if="importScanLoading"
            indeterminate
            color="primary"
            class="mb-3"
          />

          <div v-else-if="!hasScannedImport" class="text-center pa-8">
            <v-icon size="56" color="grey-lighten-1"
              >mdi-cloud-search-outline</v-icon
            >
            <p class="text-grey mt-4">{{ tm("skills.importScanPrompt") }}</p>
          </div>

          <div
            v-else-if="importScanResults.length === 0"
            class="text-center pa-8"
          >
            <v-icon size="56" color="grey-lighten-1"
              >mdi-file-search-outline</v-icon
            >
            <p class="text-grey mt-4">{{ tm("skills.importScanEmpty") }}</p>
          </div>

          <v-list v-else class="skills-import-list">
            <v-list-item
              v-for="skill in importScanResults"
              :key="getImportSkillKey(skill)"
            >
              <template #title>
                <span class="font-weight-medium">{{ skill.name }}</span>
              </template>
              <template #subtitle>
                <div class="text-caption">
                  <div>{{ skill.source }} @ {{ skill.skillId }}</div>
                  <div v-if="skill.path">
                    {{ tm("skills.path") }}: {{ skill.path }}
                  </div>
                </div>
              </template>
              <template #append>
                <v-btn
                  color="primary"
                  size="small"
                  :loading="
                    importItemLoading[getImportSkillKey(skill)] || false
                  "
                  @click="installImportSkill(skill)"
                >
                  {{ tm("skills.install") }}
                </v-btn>
              </template>
            </v-list-item>
          </v-list>
        </v-card-text>
        <v-card-actions class="d-flex justify-end px-6 pb-4">
          <v-btn variant="text" @click="importDialog = false">
            {{ tm("skills.cancel") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar
      v-model="snackbar.show"
      :timeout="3500"
      :color="snackbar.color"
      elevation="6"
    >
      {{ snackbar.message }}
    </v-snackbar>
  </div>
</template>