// Privacy lock: covers the whole window until you sign in (password, Windows Hello, a security key or a phone
// passkey). Nothing of the library shows or takes input underneath. Windows' own prompt handles the keys.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    color: Theme.black
    visible: opacity > 0.001
    opacity: Backend.locked ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutCubic } }

    property var info: ({})
    property bool busy: false
    property string error: ""
    readonly property bool forTab: Backend.lockReason === "private"     // a private tab was clicked: can be cancelled
    readonly property var kinds: {
        var seen = {}
        ;(info.keys || []).forEach(function(k) { seen[k.kind] = true })
        return [["hello", "Windows Hello"], ["key", "Security key"], ["phone", "Phone passkey"]].filter(function(k) { return seen[k[0]] })
    }
    function refresh() { info = Backend.lockInfo(); error = ""; busy = false; pw.text = "" }
    function tryPassword() { if (pw.text === "" || busy) return; busy = true; error = ""; Backend.unlockWithPassword(pw.text) }
    function tryKey(kind) { if (busy) return; busy = true; error = ""; Backend.unlockWithKey(kind) }

    Keys.onEscapePressed: if (forTab) Backend.cancelLock()
    onVisibleChanged: if (visible) {
        refresh()
        if (info.password) pw.forceActiveFocus()
        else if (kinds.length > 0) Qt.callLater(function() { root.tryKey("") })    // no password: Windows' prompt at once
    }
    Component.onCompleted: if (Backend.locked) { refresh(); if (info.password) pw.forceActiveFocus() }
    Connections {
        target: Backend
        function onUnlockResult(ok, message) { root.busy = false; if (!ok) { root.error = message; pw.selectAll(); shake.restart() } }
    }

    // nothing underneath can be clicked, scrolled or hovered while it is up
    MouseArea { anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.AllButtons; onWheel: (w) => w.accepted = true }

    ColumnLayout {
        id: card
        anchors.centerIn: parent
        width: 340
        spacing: 14
        transform: Translate { id: nudge; x: 0 }
        SequentialAnimation {
            id: shake
            NumberAnimation { target: nudge; property: "x"; to: -10; duration: 50 * Theme.motion }
            NumberAnimation { target: nudge; property: "x"; to: 8; duration: 70 * Theme.motion }
            NumberAnimation { target: nudge; property: "x"; to: -4; duration: 60 * Theme.motion }
            NumberAnimation { target: nudge; property: "x"; to: 0; duration: 60 * Theme.motion }
        }

        Image { Layout.alignment: Qt.AlignHCenter; source: "brand/icon-128.png"; sourceSize: Qt.size(128, 128)
            Layout.preferredWidth: 72; Layout.preferredHeight: 72; smooth: true; mipmap: true }
        Text { Layout.alignment: Qt.AlignHCenter; text: root.forTab ? "This tab is private" : "Media Vault is locked"
            color: Theme.text; font.pixelSize: 22; font.weight: Font.ExtraBold }
        Text { Layout.alignment: Qt.AlignHCenter; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
            color: Theme.faint; font.pixelSize: 12
            text: root.info.password ? "Enter your password" + (root.kinds.length ? ", or sign in another way." : ".")
                                     : root.forTab ? "Sign in to open your private tabs." : "Sign in to open your library." }

        RowLayout {
            visible: root.info.password === true
            Layout.fillWidth: true
            spacing: 8
            Field {
                id: pw
                Layout.fillWidth: true
                echoMode: TextInput.Password
                placeholderText: "Password"
                enabled: !root.busy
                onAccepted: root.tryPassword()
            }
            GlassButton { small: true; primary: true; label: root.busy ? "…" : "Unlock"; enabled: pw.text !== "" && !root.busy; onClicked: root.tryPassword() }
        }
        Flow {
            visible: root.kinds.length > 0
            Layout.fillWidth: true
            Layout.topMargin: root.info.password ? 4 : 0
            spacing: 8
            Repeater {
                model: root.kinds
                GlassButton { small: true; label: modelData[1]; enabled: !root.busy; onClicked: root.tryKey(modelData[0]) }
            }
        }
        GlassButton { visible: root.forTab; small: true; label: "Cancel"; Layout.alignment: Qt.AlignHCenter; enabled: !root.busy
            onClicked: Backend.cancelLock() }
        Text {
            Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
            visible: text !== ""
            text: root.busy && !root.info.password ? "Waiting for Windows…" : root.error
            color: root.busy ? Theme.faint : Theme.red; font.pixelSize: 12
        }
    }
}
