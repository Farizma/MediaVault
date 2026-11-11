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
    // closing the library window ends Media Vault (the player too). Handled here, not by connecting Python to
    // `closing`: PySide cannot pass the QQuickCloseEvent, so that slot failed and Media Vault stayed running hidden.
    onClosing: Backend.windowClosing()

    Loader {
        id: screen
        anchors.fill: parent
        source: Backend.needsSetup ? "Wizard.qml" : "Dashboard.qml"
        onLoaded: if (!Backend.needsSetup) Backend.reload()
    }
    // the size it goes back to from maximised (saved between sessions by the app)
    property rect normalGeo: Qt.rect(x, y, width, height)
    function keepNormal() { if (visibility === Window.Windowed) normalGeo = Qt.rect(x, y, width, height) }
    onXChanged: keepNormal()
    onYChanged: keepNormal()
    onWidthChanged: keepNormal()
    onHeightChanged: keepNormal()
    property int restoreTo: Window.Windowed       // minimised for picture in picture: come back as it was
    Connections {
        target: Backend
        function onRaiseWindow() {
            if (win.visibility === Window.Minimized || win.visibility === Window.Hidden) win.visibility = win.restoreTo
            win.raise(); win.requestActivate()
        }
        function onMinimizeWindow() {
            if (win.visibility !== Window.Minimized) win.restoreTo = win.visibility === Window.Maximized ? Window.Maximized : Window.Windowed
            win.showMinimized()
        }
    }
}
