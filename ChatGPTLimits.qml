import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins

PluginComponent {
    id: root

    layerNamespacePlugin: "chatgpt-limits"

    property var limitData: null
    property string statusMessage: "Загружаю лимиты…"
    property bool loading: false
    property int refreshInterval: 300000

    Timer {
        interval: root.refreshInterval
        running: true
        repeat: true
        onTriggered: root.refreshLimits()
    }

    Component.onCompleted: Qt.callLater(root.refreshLimits)

    function refreshLimits() {
        if (loading)
            return;

        if (!pluginService || !pluginId) {
            statusMessage = "Плагин ещё запускается"
            return;
        }

        const directory = pluginService.getPluginPath(pluginId);
        if (!directory) {
            statusMessage = "Не удалось найти файлы плагина"
            return;
        }

        loading = true;
        statusMessage = "Обновляю лимиты…";
        const request = requestComponent.createObject(root, { scriptPath: directory + "/fetch_limits.py" });
        request.running = true;
    }

    function handleResponse(rawText) {
        loading = false;
        try {
            const response = JSON.parse(rawText.trim());
            if (!response.ok) {
                statusMessage = response.error || "Не удалось получить лимиты";
                return;
            }
            limitData = response;
            statusMessage = response.limits.length ? "Данные из аккаунта Codex" : "Аккаунт не вернул данные о лимитах";
        } catch (error) {
            statusMessage = "Не удалось разобрать ответ Codex";
        }
    }

    function handleProcessExit(exitCode) {
        loading = false;
        if (exitCode !== 0 && !limitData)
            statusMessage = "Не удалось запустить Codex. Проверь, что команда codex доступна.";
    }

    function limitTitle(limit) {
        if (limit.name)
            return limit.name;
        if (limit.id === "codex")
            return "Основной лимит";
        if (limit.id === "codex_other")
            return "Дополнительный лимит";
        return limit.id;
    }

    function remainingText(window) {
        if (!window || window.usedPercent === undefined || window.usedPercent === null)
            return "Нет данных";
        return Math.max(0, 100 - Number(window.usedPercent)).toFixed(0) + "% осталось";
    }

    function resetText(window) {
        if (!window || !window.resetsAt)
            return "Время сброса не указано";
        return "Сброс " + Qt.formatDateTime(new Date(Number(window.resetsAt) * 1000), "dd.MM, HH:mm");
    }

    function windowName(window, fallback) {
        if (!window)
            return fallback;
        const minutes = Number(window.windowDurationMins || 0);
        if (minutes >= 10000)
            return "Неделя";
        if (minutes >= 180 && minutes <= 600)
            return "5 часов";
        if (minutes > 0 && minutes < 180)
            return "Короткое окно";
        if (minutes > 600)
            return "Длинное окно";
        return fallback;
    }

    Component {
        id: requestComponent

        Process {
            property string scriptPath: ""
            command: ["python3", scriptPath]

            stdout: StdioCollector {
                onStreamFinished: root.handleResponse(text)
            }

            stderr: StdioCollector {
                onStreamFinished: {
                    if (text.trim())
                        console.warn("ChatGPT Limits helper:", text.trim());
                }
            }

            onExited: exitCode => {
                root.handleProcessExit(exitCode);
                destroy();
            }
        }
    }

    horizontalBarPill: Component {
        Row {
            spacing: Theme.spacingXS
            anchors.verticalCenter: parent.verticalCenter

            DankIcon {
                name: "speed"
                size: Theme.iconSize - 8
                color: root.limitData?.limits?.length ? Theme.primary : Theme.surfaceVariantText
                anchors.verticalCenter: parent.verticalCenter
            }

            StyledText {
                text: root.loading ? "GPT …" : (root.limitData?.limits?.length ? "GPT " + root.remainingText(root.limitData.limits[0].primary).replace(" осталось", "") : "GPT")
                color: Theme.surfaceText
                font.pixelSize: Theme.fontSizeSmall
                font.weight: Font.Medium
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    verticalBarPill: Component {
        Column {
            spacing: 1
            anchors.horizontalCenter: parent.horizontalCenter

            DankIcon {
                name: "speed"
                size: Theme.iconSize - 8
                color: root.limitData?.limits?.length ? Theme.primary : Theme.surfaceVariantText
                anchors.horizontalCenter: parent.horizontalCenter
            }

            StyledText {
                text: root.limitData?.limits?.length ? root.remainingText(root.limitData.limits[0].primary).replace(" осталось", "") : "GPT"
                color: Theme.surfaceText
                font.pixelSize: Theme.fontSizeSmall
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    }

    popoutContent: Component {
        PopoutComponent {
            id: popout
            headerText: "Лимиты Codex"
            detailsText: root.limitData?.limits?.length ? "План " + (root.limitData.limits[0].planType || "ChatGPT") : "Использование Codex в ChatGPT"
            showCloseButton: true

            Column {
                width: parent.width
                spacing: Theme.spacingM

                StyledText {
                    width: parent.width
                    text: root.limitData?.limits?.length ? "" : root.statusMessage
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall
                    wrapMode: Text.WordWrap
                    visible: !root.limitData?.limits?.length
                }

                Repeater {
                    model: root.limitData?.limits || []

                    delegate: Column {
                        required property var modelData
                        width: parent.width
                        spacing: Theme.spacingS

                        StyledText {
                            text: root.limitTitle(modelData)
                            color: Theme.surfaceText
                            font.pixelSize: Theme.fontSizeMedium
                            font.weight: Font.Medium
                        }

                        Repeater {
                            model: [
                                { title: root.windowName(modelData.primary, "Основное окно"), value: modelData.primary },
                                { title: root.windowName(modelData.secondary, "Дополнительное окно"), value: modelData.secondary }
                            ].filter(entry => entry.value !== null && entry.value !== undefined)

                            delegate: Column {
                                required property var modelData
                                width: parent.width
                                spacing: Theme.spacingXS

                                Row {
                                    width: parent.width
                                    StyledText {
                                        width: parent.width * 0.55
                                        text: modelData.title
                                        color: Theme.surfaceVariantText
                                        font.pixelSize: Theme.fontSizeSmall
                                    }
                                    StyledText {
                                        width: parent.width * 0.45
                                        text: root.remainingText(modelData.value)
                                        color: Theme.surfaceText
                                        font.pixelSize: Theme.fontSizeSmall
                                        horizontalAlignment: Text.AlignRight
                                    }
                                }

                                StyledRect {
                                    width: parent.width
                                    height: 6
                                    radius: 3
                                    color: Theme.surfaceContainerHighest
                                    border.width: 0

                                    StyledRect {
                                        width: parent.width * Math.max(0, Math.min(100, Number(modelData.value.usedPercent || 0))) / 100
                                        height: parent.height
                                        radius: 3
                                        color: Number(modelData.value.usedPercent || 0) >= 90 ? Theme.error : Theme.primary
                                        border.width: 0
                                    }
                                }

                                StyledText {
                                    text: root.resetText(modelData.value)
                                    color: Theme.surfaceVariantText
                                    font.pixelSize: Theme.fontSizeSmall - 1
                                }
                            }
                        }
                    }
                }

                Row {
                    width: parent.width
                    spacing: Theme.spacingS

                    DankButton {
                        text: root.loading ? "Обновляю…" : "Обновить"
                        enabled: !root.loading
                        onClicked: root.refreshLimits()
                    }

                    StyledText {
                        width: parent.width - 110
                        text: root.limitData?.fetchedAt ? "Обновлено " + Qt.formatDateTime(new Date(root.limitData.fetchedAt * 1000), "HH:mm") : ""
                        color: Theme.surfaceVariantText
                        font.pixelSize: Theme.fontSizeSmall - 1
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                StyledText {
                    width: parent.width
                    text: "Данные Codex. Лимиты обычного чата ChatGPT могут учитываться отдельно."
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall - 1
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    popoutWidth: 360
    popoutHeight: 360
}
