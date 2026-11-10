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

    property var accounts: [{ id: "default", label: "Основной Codex", authenticated: false }]
    property var limitData: null
    property string statusMessage: "Загружаю аккаунты…"
    property bool loading: false
    property bool loginInProgress: false
    property int refreshInterval: 300000
    property string selectedAccountId: pluginData.selectedAccount || "default"

    readonly property var selectedAccount: {
        const found = accounts.find(account => account.id === selectedAccountId);
        return found || accounts[0] || { id: "default", label: "Основной Codex" };
    }
    readonly property string selectedAccountLabel: selectedAccount.email || selectedAccount.label || "Основной Codex"

    Timer {
        interval: root.refreshInterval
        running: true
        repeat: true
        onTriggered: root.refreshLimits()
    }

    Component.onCompleted: Qt.callLater(root.refreshAccounts)

    function helperPath() {
        if (!pluginService || !pluginId)
            return "";
        const directory = pluginService.getPluginPath(pluginId);
        return directory ? directory + "/fetch_limits.py" : "";
    }

    function runHelper(mode, args) {
        const scriptPath = helperPath();
        if (!scriptPath) {
            statusMessage = "Не удалось найти файлы плагина";
            return null;
        }
        const process = helperProcessComponent.createObject(root, {
            scriptPath: scriptPath,
            helperArgs: args,
            requestMode: mode
        });
        if (!process)
            return null;
        process.running = true;
        return process;
    }

    function refreshAccounts() {
        runHelper("list", ["list"]);
    }

    function refreshLimits() {
        if (loading || loginInProgress)
            return;
        if (!accounts.length) {
            refreshAccounts();
            return;
        }
        loading = true;
        statusMessage = "Обновляю лимиты…";
        limitData = null;
        if (!runHelper("limits", ["limits", selectedAccountId]))
            loading = false;
    }

    function selectAccount(accountId) {
        const account = accounts.find(item => item.id === accountId);
        if (!account)
            return;
        selectedAccountId = accountId;
        limitData = null;
        if (pluginService && pluginId)
            pluginService.savePluginData(pluginId, "selectedAccount", accountId);
        refreshLimits();
    }

    function beginLogin() {
        if (loginInProgress || loading)
            return;
        loginInProgress = true;
        statusMessage = "Создаю отдельный профиль Codex…";
        if (!runHelper("login", ["login"]))
            loginInProgress = false;
    }

    function consumeOutput(process, fullText) {
        const chunk = fullText.substring(process.outputOffset);
        process.outputOffset = fullText.length;
        process.outputBuffer += chunk;

        let newline = process.outputBuffer.indexOf("\n");
        while (newline >= 0) {
            const line = process.outputBuffer.substring(0, newline).trim();
            process.outputBuffer = process.outputBuffer.substring(newline + 1);
            if (line)
                handleHelperLine(process, line);
            newline = process.outputBuffer.indexOf("\n");
        }
    }

    function handleHelperLine(process, line) {
        let message;
        try {
            message = JSON.parse(line);
        } catch (error) {
            console.warn("ChatGPT Limits returned invalid JSON:", error);
            return;
        }

        if (message.ok === false || message.event === "login_error") {
            statusMessage = message.error || "Не удалось выполнить запрос Codex";
            if (process.requestMode === "login")
                loginInProgress = false;
            if (process.requestMode === "limits")
                loading = false;
            return;
        }

        if (process.requestMode === "list") {
            if (!Array.isArray(message.accounts)) {
                statusMessage = "Codex вернул неверный список аккаунтов";
                return;
            }
            accounts = message.accounts;
            const stillAvailable = accounts.some(account => account.id === selectedAccountId);
            if (!stillAvailable) {
                selectedAccountId = "default";
                if (pluginService && pluginId)
                    pluginService.savePluginData(pluginId, "selectedAccount", "default");
            }
            statusMessage = accounts.length ? "Выбери аккаунт для просмотра лимита" : "Аккаунты не найдены";
            if (!loginInProgress)
                refreshLimits();
            return;
        }

        if (process.requestMode === "limits") {
            loading = false;
            if (message.accountId !== selectedAccountId) {
                refreshLimits();
                return;
            }
            limitData = message;
            statusMessage = message.limits.length ? "Данные из выбранного аккаунта" : "Аккаунт не вернул данные о лимитах";
            return;
        }

        if (process.requestMode === "login" && message.event === "login_started") {
            statusMessage = "Заверши вход в открывшемся окне браузера";
            Quickshell.execDetached(["xdg-open", message.authUrl]);
            return;
        }

        if (process.requestMode === "login" && message.event === "login_completed") {
            loginInProgress = false;
            statusMessage = "Аккаунт добавлен: " + (message.email || "ChatGPT");
            selectedAccountId = message.profileId;
            if (pluginService && pluginId)
                pluginService.savePluginData(pluginId, "selectedAccount", message.profileId);
            refreshAccounts();
        }
    }

    function finishHelper(process, exitCode) {
        if (process.outputBuffer.trim())
            handleHelperLine(process, process.outputBuffer.trim());
        if (process.requestMode === "login" && exitCode !== 0) {
            loginInProgress = false;
            if (statusMessage === "Заверши вход в открывшемся окне браузера")
                statusMessage = "Вход не завершён. Попробуй добавить аккаунт ещё раз.";
        } else if (process.requestMode === "limits" && exitCode !== 0) {
            loading = false;
        } else if (process.requestMode === "list" && exitCode !== 0 && !accounts.length) {
            statusMessage = "Не удалось запустить Codex. Проверь установку Codex CLI.";
        }
    }

    function remainingPercent(window) {
        if (!window || window.usedPercent === undefined || window.usedPercent === null)
            return 0;
        var usedPercent = Number(window.usedPercent);
        if (!isFinite(usedPercent))
            return 0;
        return Math.max(0, Math.min(100, 100 - usedPercent));
    }

    function remainingText(window) {
        if (!window || window.usedPercent === undefined || window.usedPercent === null)
            return "Нет данных";
        return remainingPercent(window).toFixed(0) + "% осталось";
    }

    function resetText(window) {
        if (!window || !window.resetsAt)
            return "Время сброса не указано";
        return "Сброс " + Qt.formatDateTime(new Date(Number(window.resetsAt) * 1000), "dd.MM, HH:mm");
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
        id: helperProcessComponent

        Process {
            id: helperProcess
            property string scriptPath: ""
            property var helperArgs: []
            property string requestMode: ""
            property int outputOffset: 0
            property string outputBuffer: ""

            command: ["python3", scriptPath].concat(helperArgs)

            stdout: StdioCollector {
                onTextChanged: root.consumeOutput(helperProcess, text)
                onStreamFinished: root.consumeOutput(helperProcess, text)
            }

            stderr: StdioCollector {
                onStreamFinished: {
                    if (text.trim())
                        console.warn("ChatGPT Limits helper:", text.trim());
                }
            }

            onExited: exitCode => {
                root.finishHelper(helperProcess, exitCode);
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
            headerText: "Лимиты Codex"
            detailsText: root.selectedAccountLabel
            showCloseButton: true

            Column {
                width: parent.width
                spacing: Theme.spacingM

                StyledText {
                    width: parent.width
                    text: "Аккаунт"
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall
                    font.weight: Font.Medium
                }

                Column {
                    width: parent.width
                    spacing: Theme.spacingXS

                    Repeater {
                        model: root.accounts

                        delegate: StyledRect {
                            required property var modelData
                            width: parent.width
                            height: 44
                            radius: Theme.cornerRadius
                            color: modelData.id === root.selectedAccountId ? Theme.surfaceContainerHighest : Theme.surfaceContainerHigh
                            border.width: 0

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.spacingM
                                anchors.rightMargin: Theme.spacingM
                                spacing: Theme.spacingS

                                DankIcon {
                                    name: modelData.id === root.selectedAccountId ? "check_circle" : "account_circle"
                                    size: Theme.iconSize - 6
                                    color: modelData.id === root.selectedAccountId ? Theme.primary : Theme.surfaceVariantText
                                    anchors.verticalCenter: parent.verticalCenter
                                }

                                Column {
                                    width: parent.width - Theme.iconSize - Theme.spacingS
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 1

                                    StyledText {
                                        width: parent.width
                                        text: modelData.email || modelData.label || "Основной Codex"
                                        color: Theme.surfaceText
                                        font.pixelSize: Theme.fontSizeSmall
                                        elide: Text.ElideRight
                                    }

                                    StyledText {
                                        width: parent.width
                                        text: modelData.planType || (modelData.id === "default" ? "Системный профиль Codex" : "ChatGPT")
                                        color: Theme.surfaceVariantText
                                        font.pixelSize: Theme.fontSizeSmall - 1
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.selectAccount(modelData.id)
                            }
                        }
                    }
                }

                DankButton {
                    width: parent.width
                    text: root.loginInProgress ? "Ожидаю вход в браузере…" : "Добавить аккаунт"
                    iconName: "person_add"
                    enabled: !root.loginInProgress && !root.loading
                    onClicked: root.beginLogin()
                }

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
                                        width: parent.width * root.remainingPercent(modelData.value) / 100
                                        height: parent.height
                                        radius: 3
                                        color: root.remainingPercent(modelData.value) <= 10 ? Theme.error : Theme.primary
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
                        text: root.loading ? "Обновляю…" : "Обновить лимит"
                        iconName: "refresh"
                        enabled: !root.loading && !root.loginInProgress
                        onClicked: root.refreshLimits()
                    }

                    StyledText {
                        width: parent.width - 150
                        text: root.limitData?.fetchedAt ? "Обновлено " + Qt.formatDateTime(new Date(root.limitData.fetchedAt * 1000), "HH:mm") : ""
                        color: Theme.surfaceVariantText
                        font.pixelSize: Theme.fontSizeSmall - 1
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                StyledText {
                    width: parent.width
                    text: "Показываются лимиты Codex этого аккаунта; лимиты обычного чата ChatGPT могут учитываться отдельно."
                    color: Theme.surfaceVariantText
                    font.pixelSize: Theme.fontSizeSmall - 1
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    popoutWidth: 380
    popoutHeight: 540
}
