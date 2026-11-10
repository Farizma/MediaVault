import QtQuick
import QtQuick.Window

Window {
    id: win
    visible: true
    width: 1360
    height: 860
    minimumWidth: 960
    minimumHeight: 640
    title: "Media Vault"
    color: Theme.black

    Loader {
        id: screen
        anchors.fill: parent
        source: Backend.needsSetup ? "Wizard.qml" : "Dashboard.qml"
        onLoaded: if (!Backend.needsSetup) Backend.reload()
    }
    Connections {
        target: Backend
        function onRaiseWindow() { win.show(); win.raise(); win.requestActivate() }
    }
}
