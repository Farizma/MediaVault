// Theater HUD: a transparent window laid over the native mpv / VLC window, owned by it (so it is always above the
// video, never behind it, and minimises with it). It owns ALL input. The player underneath receives none.
// shortcut: the glass is translucent, not blurred: the video lives in another native window,
// so a Qt blur cannot sample it.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../ui"

Window {
    id: win
    readonly property var st: Player.state
    flags: Qt.FramelessWindowHint | Qt.Tool | (st.pip === true ? Qt.WindowStaysOnTopHint : 0)
    color: "transparent"
    visible: st.active === true
    x: st.x || 0
    y: st.y || 0
    width: st.w || 1280
    height: st.h || 720
    onWidthChanged: root.popup = ""            // the picker is placed over its button; a resize moves the button
    onVisibleChanged: if (visible) { root.popup = ""; root.forceActiveFocus(); requestActivate(); root.poke() }

    // Windows passes clicks on fully transparent pixels of a see-through window to whatever is underneath, so a HUD
    // that is clear except for its controls cannot be dragged (PiP) or clicked to pause. Black at 1/255 is invisible
    // over the video and makes every pixel catch the mouse.
    Rectangle { anchors.fill: parent; color: "#01000000"; z: -1000 }

    // lists change only when their content does, so open pickers do not flicker on every tick
    property var subs: []
    property var audios: []
    property var videos: []
    property string subsJson: ""
    property string audiosJson: ""
    property string videosJson: ""
    property int lastToast: 0
    onStChanged: {
        var a = JSON.stringify(st.subs || [])
        if (a !== subsJson) { subsJson = a; subs = st.subs || [] }
        var b = JSON.stringify(st.audio || [])
        if (b !== audiosJson) { audiosJson = b; audios = st.audio || [] }
        var v = JSON.stringify(st.video || [])
        if (v !== videosJson) { videosJson = v; videos = st.video || [] }
        if (st.toastId !== undefined && st.toastId !== lastToast) {
            lastToast = st.toastId
            if (st.toast) { toastLabel.text = st.toast; toast.opacity = 1; toastHide.restart() }
        }
    }

    function fmt(s) {
        s = Math.max(0, Math.floor(s || 0))
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60
        return (h > 0 ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (r < 10 ? "0" : "") + r
    }

    Item {
        id: root
        anchors.fill: parent
        focus: true
        property bool controlsOn: true
        property string popup: ""          // "", "panel" (Audio & Video), "camera" (snapshot), "cast"
        property var castList: []
        Connections { target: Backend; function onDevicesFound(list) { root.castList = list } }
        readonly property bool cropping: (win.st.snapshot || "") !== ""
        readonly property bool shrunk: (win.st.autoplayLeft || 0) > 0
        readonly property bool pip: win.st.pip === true
        // the button a pop-up belongs to: it grows out of that button and shrinks back into it
        property real originX: 0
        property real originY: 0
        property real anchorRight: 0
        function poke() { controlsOn = true; idle.restart() }
        function togglePopup(name, button) {
            if (popup === name) { popup = ""; return }
            var p = button.mapToItem(root, button.width / 2, button.height / 2)
            originX = p.x; originY = p.y
            anchorRight = button.mapToItem(root, button.width, 0).x
            popup = name
        }

        // ---- volume: the HUD shows its own value at once; the player catches up
        property int vol: 100
        property int volBeforeMute: 100
        property real wheelAcc: 0
        function toggleMute() { if (vol > 0) { volBeforeMute = vol; setVol(0) } else setVol(Math.max(5, volBeforeMute)) }
        function setVol(v) {
            vol = Math.max(0, Math.min(100, Math.round(v)))
            Player.setVolume(vol)
            volPill.ping()
        }
        Connections { target: win; function onStChanged() { if (!volPill.active && win.st.volume !== undefined) root.vol = win.st.volume } }

        Timer { id: idle; interval: 3000; onTriggered: if (!root.cropping && root.popup === "" && !win.st.paused) root.controlsOn = false }

        Keys.onPressed: (e) => {
            root.poke()
            if (root.cropping) { if (e.key === Qt.Key_Escape) Player.cancelSnapshot(); return }
            switch (e.key) {
            case Qt.Key_Space: Player.togglePause(); break
            case Qt.Key_Left: Player.seekBy(-10); break
            case Qt.Key_Right: Player.seekBy(10); break
            case Qt.Key_Up: root.setVol(root.vol + 5); break
            case Qt.Key_M: root.toggleMute(); break
            case Qt.Key_Down: root.setVol(root.vol - 5); break
            case Qt.Key_N: Player.toggleNight(); break
            case Qt.Key_U: Player.setLevel((win.st.level || 1) % 3 + 1); break
            case Qt.Key_Tab: if (win.st.creditsActive) Player.finishNow(); else Player.skipIntro(); break
            case Qt.Key_O: Player.markCredits(); break
            case Qt.Key_P: root.popup = ""; Player.togglePip(); break
            case Qt.Key_B: Player.toggleBlackout(); break
            case Qt.Key_BracketLeft: Player.setSpeed((win.st.speed || 1) - 0.25); break
            case Qt.Key_BracketRight: Player.setSpeed((win.st.speed || 1) + 0.25); break
            case Qt.Key_Backslash: Player.setSpeed(1); break
            case Qt.Key_Z: Player.setSubDelay((win.st.subDelay || 0) - 0.1); break
            case Qt.Key_X: Player.setSubDelay((win.st.subDelay || 0) + 0.1); break
            case Qt.Key_Minus: Player.setAudioDelay((win.st.audioDelay || 0) - 0.05); break
            case Qt.Key_Equal: case Qt.Key_Plus: Player.setAudioDelay((win.st.audioDelay || 0) + 0.05); break
            case Qt.Key_Return: case Qt.Key_Enter: Player.nextNow(); break
            case Qt.Key_C: Player.captureFrame((e.modifiers & Qt.ShiftModifier) ? "fanart" : "poster"); break
            case Qt.Key_I: Player.markIntro(); break
            case Qt.Key_V: Player.cycleVrView(); break
            case Qt.Key_F: Player.toggleFullscreen(); break
            case Qt.Key_Escape: if (root.popup !== "") root.popup = ""; else if (root.pip) Player.togglePip(); else if (win.st.fullscreen) Player.toggleFullscreen(); else Player.stop(); break
            }
            e.accepted = true
        }

        // click anywhere that is not a control: pause / play, and wake the HUD
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: root.controlsOn ? Qt.ArrowCursor : Qt.BlankCursor
            onPositionChanged: root.poke()
            acceptedButtons: Qt.LeftButton | Qt.MiddleButton
            // wheel click (middle button): full screen on / off, at once (no pause, no double-click wait)
            onPressed: (m) => { if (m.button === Qt.MiddleButton && !root.cropping && !root.pip) { root.poke(); Player.toggleFullscreen() } }
            onClicked: (m) => { if (m.button !== Qt.LeftButton) return
                                if (root.popup !== "") root.popup = ""; else if (!root.cropping) Player.togglePause() }
            onDoubleClicked: (m) => { if (m.button === Qt.LeftButton && !root.cropping) { Player.togglePause(); Player.toggleFullscreen() } }   // the click before it paused: undo that
            // scroll anywhere over the picture = volume, 5 % a notch (touchpads add up their small steps).
            // The Audio & Video panel swallows its own wheel events, so scrolling there never lands here.
            onWheel: (w) => {
                if (root.cropping) return
                root.wheelAcc += w.angleDelta.y
                var steps = root.wheelAcc > 0 ? Math.floor(root.wheelAcc / 120) : Math.ceil(root.wheelAcc / 120)
                if (steps !== 0) { root.wheelAcc -= steps * 120; root.setVol(root.vol + steps * 5) }
            }
        }

        // ---------------------------------------------------------------- top bar
        Rectangle {
            id: top
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 120
            opacity: root.controlsOn && !root.cropping && !root.shrunk && !root.pip ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion; easing.type: Easing.OutCubic } }
            gradient: Gradient {
                GradientStop { position: 0; color: "#CC000000" }
                GradientStop { position: 1; color: "transparent" }
            }
            RowLayout {
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 28 }
                spacing: 14
                GlassButton { tip: "Back to the library (Esc)"; label: "Back"; glyph: "\u2039"; small: true; onClicked: Player.stop() }
                Text {
                    Layout.fillWidth: true
                    text: win.st.title || ""
                    color: Theme.text; font.pixelSize: 18; font.weight: Font.Bold; font.letterSpacing: -0.3
                    elide: Text.ElideRight
                }
                Rectangle {
                    implicitWidth: coreText.implicitWidth + 16; implicitHeight: 22; radius: 6
                    color: Theme.lineStrong
                    Text { id: coreText; anchors.centerIn: parent; text: (win.st.core || "").toUpperCase() + " CORE"; color: Theme.soft; font.family: Theme.mono; font.pixelSize: 11; font.weight: Font.DemiBold }
                }
            }
        }

        // ---------------------------------------------------------------- bottom control bar
        Rectangle {
            id: bar
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: win.width < 1100 ? 16 : 28 }
            height: barCol.implicitHeight + 32
            radius: 16
            color: Theme.hud
            border.color: Theme.line
            opacity: root.controlsOn && !root.cropping && !root.shrunk && !root.pip ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion; easing.type: Easing.OutCubic } }

            ColumnLayout {
                id: barCol
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Text { text: win.fmt(win.st.position); color: Theme.text; font.family: Theme.mono; font.pixelSize: 12; Layout.preferredWidth: 64 }
                    Slider {
                        id: seek
                        Layout.fillWidth: true
                        from: 0; to: Math.max(1, win.st.duration || 1)
                        value: win.st.position || 0
                        onMoved: Player.seekTo(value)
                        background: Rectangle {
                            x: seek.leftPadding; y: seek.topPadding + seek.availableHeight / 2 - height / 2
                            width: seek.availableWidth; height: seek.hovered || seek.pressed ? 8 : 5; radius: height / 2; color: Theme.edge
                            Behavior on height { NumberAnimation { duration: 120 * Theme.motion } }
                            Rectangle { width: seek.visualPosition * parent.width; height: parent.height; radius: parent.radius; color: Theme.green }
                        }
                        handle: Rectangle {
                            x: seek.leftPadding + seek.visualPosition * (seek.availableWidth - width)
                            y: seek.topPadding + seek.availableHeight / 2 - height / 2
                            width: 16; height: 16; radius: 8; color: Theme.text
                            scale: seek.pressed ? 1.25 : 1
                            Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
                        }
                    }
                    Text { text: "-" + win.fmt((win.st.duration || 0) - (win.st.position || 0)); color: Theme.faint; font.family: Theme.mono; font.pixelSize: 12; Layout.preferredWidth: 64; horizontalAlignment: Text.AlignRight }
                }
                // playback on the left; snapshot and the Audio & Video panel on the right
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    GlassButton { label: win.st.paused ? "Play" : "Pause"; glyph: win.st.paused ? "\u25B6" : "\u275A\u275A"; primary: true; Layout.preferredWidth: 104; implicitHeight: 48; radius: 14; onClicked: Player.togglePause() }
                    RevealButton { tip: "Shortcut  \u2190"; iconKind: "back"; label: "Back 10s"; onClicked: Player.seekBy(-10) }
                    RevealButton { tip: "Shortcut  \u2192"; iconKind: "forward"; label: "Forward 10s"; onClicked: Player.seekBy(10) }
                    // volume, right by the playback buttons: speaker (click = mute), slider, percentage
                    Rectangle {
                        Layout.leftMargin: 6
                        implicitWidth: volRow.implicitWidth + 24; implicitHeight: 48; radius: 14
                        color: Theme.fillHover; border.color: Theme.lineStrong
                        Row {
                            id: volRow
                            anchors.centerIn: parent
                            spacing: 8
                            Speaker {
                                level: root.vol; anchors.verticalCenter: parent.verticalCenter
                                MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: root.toggleMute() }
                            }
                            Slider {
                                id: barVol
                                width: win.width < 1100 ? 90 : 130
                                anchors.verticalCenter: parent.verticalCenter
                                from: 0; to: 100; stepSize: 1
                                value: root.vol
                                onMoved: root.setVol(value)
                                background: Rectangle {
                                    x: barVol.leftPadding; y: barVol.topPadding + barVol.availableHeight / 2 - height / 2
                                    width: barVol.availableWidth; height: barVol.hovered || barVol.pressed ? 6 : 4; radius: 3; color: Theme.edge
                                    Behavior on height { NumberAnimation { duration: 120 * Theme.motion } }
                                    Rectangle { width: barVol.visualPosition * parent.width; height: parent.height; radius: 3; color: Theme.green }
                                }
                                handle: Rectangle {
                                    x: barVol.leftPadding + barVol.visualPosition * (barVol.availableWidth - width)
                                    y: barVol.topPadding + barVol.availableHeight / 2 - height / 2
                                    width: 14; height: 14; radius: 7; color: Theme.text
                                    scale: barVol.pressed ? 1.2 : 1
                                    Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
                                }
                            }
                            Text { text: root.vol + "%"; width: 34; color: Theme.text; font.family: Theme.mono; font.pixelSize: 12
                                horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    RevealButton { tip: "AirPlay or Chromecast"; id: castBtn; label: "Cast"; iconKind: "airplay"; active: root.popup === "cast"
                        onClicked: { root.castList = Backend.devices(); if (root.castList.length === 0) Backend.findDevices(); root.togglePopup("cast", castBtn) } }
                    RevealButton { tip: (win.st.screens || 1) > 1 ? "Shortcut  B" : "Only one screen is connected"; iconKind: "blackout"; label: "Black Out"
                        toggled: win.st.blackout === true; opacity: (win.st.screens || 1) > 1 ? 1 : 0.45
                        onClicked: Player.toggleBlackout() }
                    RevealButton { tip: "Shortcut  F, double-click or wheel-click the picture"; iconKind: win.st.fullscreen ? "windowed" : "fullscreen"
                        label: win.st.fullscreen ? "Exit full screen" : "Full screen"; onClicked: Player.toggleFullscreen() }
                    RevealButton { tip: "Shortcut  P"; id: pipBtn; label: "Picture in picture"; iconKind: "pip"; onClicked: { root.popup = ""; Player.togglePip() } }
                    RevealButton { tip: "Use this frame as box art or fanart (C)"; id: snapBtn; label: "Snapshot"; iconKind: "snapshot"; iconColor: Theme.blue
                        active: root.popup === "camera"; onClicked: root.togglePopup("camera", snapBtn) }
                    RevealButton { tip: "Tracks, subtitles, speed, upscaling"; id: panelBtn; label: "Audio & Video"; iconKind: "panel"; iconColor: Theme.green
                        active: root.popup === "panel"; onClicked: root.togglePopup("panel", panelBtn) }
                }
            }
        }

        // ---------------------------------------------------------------- Audio & Video panel
        // Grows out of its button and shrinks back into it. Scrolling over it scrolls the panel, never the volume.
        component Row2: Rectangle {        // one choice in a list: label + tick
            id: choice
            property string label
            property bool on
            signal picked()
            Layout.fillWidth: true
            height: 34; radius: 8
            color: choiceArea.containsMouse ? Theme.fillHover : "transparent"
            Text { anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 10; rightMargin: 30 }
                text: choice.label; elide: Text.ElideRight; font.pixelSize: 13
                color: choice.on ? Theme.text : Theme.soft; font.weight: choice.on ? Font.Bold : Font.Normal }
            Text { visible: choice.on; anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                text: "\u2713"; color: Theme.green; font.pixelSize: 14; font.weight: Font.Bold }
            MouseArea { id: choiceArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: choice.picked() }
        }
        component Speaker: Canvas {           // speaker with 0-3 sound waves for the level; a cross when muted
            id: spk
            property int level: 100
            width: 24; height: 20
            // 0 = muted (cross); 1-24 no waves; 25-49 one; 50-74 two; 75+ three
            property int waves: level <= 0 ? -1 : Math.min(3, Math.floor(level / 25))
            onWavesChanged: requestPaint()
            onPaint: {
                var c = getContext("2d"); c.reset()
                c.fillStyle = Theme.text; c.strokeStyle = Theme.text; c.lineWidth = 1.7; c.lineCap = "round"
                c.beginPath(); c.moveTo(1, 7); c.lineTo(4.5, 7); c.lineTo(9, 3); c.lineTo(9, 17); c.lineTo(4.5, 13); c.lineTo(1, 13); c.closePath(); c.fill()
                if (waves < 0) { c.beginPath(); c.moveTo(13, 7); c.lineTo(19, 13); c.moveTo(19, 7); c.lineTo(13, 13); c.stroke(); return }
                for (var i = 0; i < waves; i++) { c.beginPath(); c.arc(9, 10, 4 + i * 3.6, -Math.PI / 3.4, Math.PI / 3.4); c.stroke() }
            }
        }
        component Slim: Slider {               // the HUD's slim white slider
            id: sl
            background: Rectangle {
                x: sl.leftPadding; y: sl.topPadding + sl.availableHeight / 2 - height / 2
                width: sl.availableWidth; height: 4; radius: 2; color: Theme.edge
                Rectangle { width: sl.visualPosition * parent.width; height: parent.height; radius: 2; color: Theme.green }
            }
            handle: Rectangle {
                x: sl.leftPadding + sl.visualPosition * (sl.availableWidth - width)
                y: sl.topPadding + sl.availableHeight / 2 - height / 2
                width: 14; height: 14; radius: 7; color: Theme.text
                scale: sl.pressed ? 1.2 : 1
                Behavior on scale { NumberAnimation { duration: 120 * Theme.motion } }
            }
        }
        component Head: Text { color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10; Layout.topMargin: 8 }

        // a track list as a dropdown: shows the chosen track, opens a dark list
        component Drop: ComboBox {
            id: drop
            property var tracks: []
            signal pickedId(int id)
            Layout.fillWidth: true
            implicitHeight: 38
            model: tracks
            textRole: "title"
            enabled: tracks.length > 1
            currentIndex: { for (var i = 0; i < tracks.length; i++) if (tracks[i].on) return i; return tracks.length ? 0 : -1 }
            displayText: tracks.length ? (currentIndex >= 0 ? tracks[currentIndex].title : "") : "None"
            onActivated: (i) => drop.pickedId(tracks[i].id)
            font.pixelSize: 13
            background: Rectangle {
                radius: 10
                color: drop.pressed || drop.popup.visible ? Theme.fillHover : (drop.hovered && drop.enabled ? Theme.fillHover : Theme.fillHover)
                border.color: drop.popup.visible ? Theme.blue : Theme.line
            }
            contentItem: Text {
                leftPadding: 12; rightPadding: 30
                text: drop.displayText; color: drop.enabled ? Theme.text : Theme.faint
                font.pixelSize: 13; font.weight: Font.Medium
                verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
            }
            indicator: Text {
                x: drop.width - width - 12; anchors.verticalCenter: parent.verticalCenter
                text: "\u2304"; color: drop.enabled ? Theme.dim : "transparent"; font.pixelSize: 14
                rotation: drop.popup.visible ? 180 : 0
                Behavior on rotation { NumberAnimation { duration: 180 * Theme.motion; easing.type: Easing.OutCubic } }
            }
            delegate: ItemDelegate {
                width: drop.width - 8
                height: 34
                highlighted: drop.highlightedIndex === index
                background: Rectangle { radius: 8; color: parent.highlighted ? Theme.fillHover : "transparent" }
                contentItem: Item {
                    Text { anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; rightMargin: 22 }
                        text: modelData.title; elide: Text.ElideRight; font.pixelSize: 13
                        color: modelData.on ? Theme.text : Theme.soft; font.weight: modelData.on ? Font.Bold : Font.Normal }
                    Text { visible: modelData.on === true; anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        text: "\u2713"; color: Theme.green; font.pixelSize: 13; font.weight: Font.Bold }
                }
            }
            popup: Popup {
                y: drop.height + 6
                width: drop.width
                implicitHeight: Math.min(contentItem.implicitHeight + 8, 260)
                padding: 4
                // drops open from the field: a short scale + fade from the top edge
                enter: Transition { ParallelAnimation {
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 * Theme.motion }
                    NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: 200 * Theme.motion; easing.type: Easing.OutCubic } } }
                exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 120 * Theme.motion } }
                transformOrigin: Item.Top
                contentItem: ListView { clip: true; implicitHeight: contentHeight; model: drop.popup.visible ? drop.delegateModel : null
                    currentIndex: drop.highlightedIndex; ScrollIndicator.vertical: ScrollIndicator {} }
                background: Rectangle { radius: 12; color: Theme.panel; border.color: Theme.edge }
            }
        }

        Rectangle {
            id: panel
            property real shown: root.popup === "panel" && bar.visible ? 1 : 0
            property int tab: 0                        // 0 = Audio, 1 = Video
            Behavior on shown { NumberAnimation { duration: (panel.shown < 0.5 ? 280 : 190) * Theme.motion; easing.type: Easing.OutCubic } }
            visible: shown > 0.01
            width: 320
            height: Math.min(panelCol.implicitHeight + 28, bar.y - 90)
            x: Math.max(16, Math.min(root.anchorRight - width, parent.width - width - 16))
            y: bar.y - height - 12
            radius: 16
            color: Theme.panel
            border.color: Theme.edge
            opacity: Math.min(1, shown * 1.6)
            transform: Scale { origin.x: root.originX - panel.x; origin.y: root.originY - panel.y; xScale: 0.08 + 0.92 * panel.shown; yScale: xScale }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (w) => w.accepted = true }   // scrolling here never changes the volume
            Behavior on height { NumberAnimation { duration: 220 * Theme.motion; easing.type: Easing.OutCubic } }
            onVisibleChanged: if (!visible) { audioDrop.popup.close(); videoDrop.popup.close(); subDrop.popup.close() }

            Flickable {
                id: panelFlick
                anchors { fill: parent; margins: 14 }
                contentHeight: panelCol.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
            ColumnLayout {
                id: panelCol
                width: panelFlick.width - 8
                spacing: 6
                // Audio | Video: a segmented control whose white pill slides between the two
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 34; radius: 10
                    color: "#99000000"; border.color: Theme.line
                    Rectangle {
                        width: (parent.width - 8) / 2; height: parent.height - 8; y: 4; radius: 7; color: Theme.text
                        x: 4 + panel.tab * width
                        Behavior on x { NumberAnimation { duration: 260 * Theme.motion; easing.type: Easing.OutCubic } }
                    }
                    Row {
                        anchors { fill: parent; margins: 4 }
                        Repeater {
                            model: ["Audio", "Video"]
                            Item {
                                width: parent.width / 2; height: parent.height
                                Text { anchors.centerIn: parent; text: modelData; font.pixelSize: 12; font.weight: Font.Bold
                                    color: panel.tab === index ? Theme.black : Theme.dim
                                    Behavior on color { ColorAnimation { duration: 200 * Theme.motion } } }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: panel.tab = index }
                            }
                        }
                    }
                }

                // ---- Audio
                ColumnLayout {
                    visible: panel.tab === 0
                    Layout.fillWidth: true
                    spacing: 6
                    Head { text: "AUDIO TRACK" }
                    Drop { id: audioDrop; tracks: win.audios; onPickedId: (id) => Player.setAudio(id) }
                    // lip sync: 50 ms steps (- / = on the keyboard). Kept for the next videos: it belongs to your speakers
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 4
                        spacing: 6
                        Text { text: "Audio delay"; color: Theme.soft; font.pixelSize: 12; Layout.fillWidth: true }
                        GlassButton { small: true; label: "\u2212"; implicitWidth: 34; onClicked: Player.setAudioDelay((win.st.audioDelay || 0) - 0.05) }
                        Text { text: ((win.st.audioDelay || 0) >= 0 ? "+" : "\u2212") + Math.round(Math.abs(win.st.audioDelay || 0) * 1000) + " ms"; color: Theme.text
                            font.family: Theme.mono; font.pixelSize: 12; Layout.preferredWidth: 58; horizontalAlignment: Text.AlignHCenter }
                        GlassButton { small: true; label: "+"; implicitWidth: 34; onClicked: Player.setAudioDelay((win.st.audioDelay || 0) + 0.05) }
                        GlassButton { small: true; label: "Reset"; visible: (win.st.audioDelay || 0) !== 0; onClicked: Player.setAudioDelay(0) }
                    }
                    Head { text: "SUBTITLES" }
                    Drop { id: subDrop; tracks: win.subs; onPickedId: (id) => Player.setSub(id) }
                    GlassButton { small: true; label: "Find subtitles online"; Layout.topMargin: 4
                        tip: "Search OpenSubtitles for this video and switch the best match on"; onClicked: Player.findSubtitles() }
                    // timing: nudge in 0.1 s steps (Z / X on the keyboard)
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 4
                        spacing: 6
                        Text { text: "Timing"; color: Theme.soft; font.pixelSize: 12; Layout.fillWidth: true }
                        GlassButton { small: true; label: "\u2212"; implicitWidth: 34; onClicked: Player.setSubDelay((win.st.subDelay || 0) - 0.1) }
                        Text { text: ((win.st.subDelay || 0) >= 0 ? "+" : "") + (win.st.subDelay || 0).toFixed(1) + " s"; color: Theme.text
                            font.family: Theme.mono; font.pixelSize: 12; Layout.preferredWidth: 58; horizontalAlignment: Text.AlignHCenter }
                        GlassButton { small: true; label: "+"; implicitWidth: 34; onClicked: Player.setSubDelay((win.st.subDelay || 0) + 0.1) }
                        GlassButton { small: true; label: "Reset"; visible: (win.st.subDelay || 0) !== 0; onClicked: Player.setSubDelay(0) }
                    }
                    // style (MPV): size, height on screen, box behind the text
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        enabled: win.st.subStyleOk === true
                        opacity: enabled ? 1 : 0.45
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "Size"; color: Theme.soft; font.pixelSize: 12; Layout.preferredWidth: 58 }
                            Slim { id: subSize; Layout.fillWidth: true; from: 0.5; to: 2.5; stepSize: 0.05; value: win.st.subScale || 1
                                onMoved: Player.setSubStyle(value, win.st.subPos || 100, win.st.subBox === true) }
                            Text { text: Math.round((win.st.subScale || 1) * 100) + "%"; color: Theme.text; font.family: Theme.mono; font.pixelSize: 11; Layout.preferredWidth: 40; horizontalAlignment: Text.AlignRight }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: "Height"; color: Theme.soft; font.pixelSize: 12; Layout.preferredWidth: 58 }
                            // 100 = bottom edge; lower values lift the text up the picture
                            Slim { Layout.fillWidth: true; from: 100; to: 50; stepSize: 1; value: win.st.subPos || 100
                                onMoved: Player.setSubStyle(win.st.subScale || 1, value, win.st.subBox === true) }
                            Text { text: (100 - (win.st.subPos || 100)) + "%"; color: Theme.text; font.family: Theme.mono; font.pixelSize: 11; Layout.preferredWidth: 40; horizontalAlignment: Text.AlignRight }
                        }
                        Toggle { Layout.fillWidth: true; text: "Dark box behind subtitles"; checked: win.st.subBox === true
                            onToggled: Player.setSubStyle(win.st.subScale || 1, win.st.subPos || 100, checked) }
                    }
                    Text { visible: win.st.subStyleOk !== true; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 11
                        text: "Subtitle size and position need the MPV engine; timing works on both." }
                    Toggle { Layout.fillWidth: true; Layout.topMargin: 8; text: "Reduce loud sounds"; hint: "Evens out explosions and whispers"
                        checked: win.st.night === true; onToggled: Player.toggleNight() }
                }

                // ---- Video
                ColumnLayout {
                    visible: panel.tab === 1
                    Layout.fillWidth: true
                    spacing: 6
                    Head { text: "VIDEO TRACK" }
                    Drop { id: videoDrop; tracks: win.videos; onPickedId: (id) => Player.setVideo(id) }
                    Head { text: "SPEED" }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Slim {
                            id: speedSlider
                            Layout.fillWidth: true
                            from: 0.5; to: 3; stepSize: 0.05
                            value: win.st.speed || 1
                            onMoved: Player.setSpeed(value)
                        }
                        Text { text: (win.st.speed || 1).toFixed(2).replace(/0$/, "") + "\u00D7"; color: Theme.text; font.family: Theme.mono; font.pixelSize: 12
                            Layout.preferredWidth: 44; horizontalAlignment: Text.AlignRight }
                        GlassButton { small: true; label: "1\u00D7"; visible: (win.st.speed || 1) !== 1; onClicked: Player.setSpeed(1) }
                    }
                    Head { text: "UPSCALING" }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6
                        visible: win.st.core === "mpv"
                        Repeater {
                            model: 3
                            Pill { label: ["Standard", "High quality", "AI Ultra"][index]; selected: win.st.level === index + 1; accent: Theme.blue
                                onClicked: Player.setLevel(index + 1) }
                        }
                    }
                    Text { visible: win.st.core !== "mpv"; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 12
                        text: "Upscaling needs the MPV engine (Settings \u203A Playback)." }
                    Toggle { visible: win.st.vr === true; Layout.fillWidth: true; Layout.topMargin: 8; text: "VR: both eyes side by side"; hint: "Off: left eye only, flat"
                        checked: win.st.vrView === "sbs"; onToggled: Player.cycleVrView() }
                    // HDR: fit into this screen (tone mapping), or send HDR untouched to an HDR screen
                    RowLayout {
                        Layout.fillWidth: true
                        Head { text: "HDR"; Layout.fillWidth: true }
                        Rectangle {
                            visible: (win.st.hdr || "") !== ""
                            implicitWidth: hdrBadge.implicitWidth + 12; implicitHeight: 18; radius: 5
                            color: "transparent"; border.color: Theme.amber
                            Text { id: hdrBadge; anchors.centerIn: parent; text: win.st.hdr || ""; color: Theme.amber; font.family: Theme.mono; font.pixelSize: 10; font.weight: Font.Bold }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        visible: win.st.hdrOk === true
                        Flow {
                            Layout.fillWidth: true
                            spacing: 6
                            Pill { label: "Fit to this screen"; selected: win.st.hdrMode !== "display"; accent: Theme.blue
                                onClicked: Player.setHdr("tonemap", win.st.hdrPeak || 0, win.st.hdrScene !== false) }
                            Pill { label: "HDR screen"; selected: win.st.hdrMode === "display"; accent: Theme.blue
                                onClicked: Player.setHdr("display", win.st.hdrPeak || 0, win.st.hdrScene !== false) }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            visible: win.st.hdrMode !== "display"
                            Text { text: "Brightness"; color: Theme.soft; font.pixelSize: 12; Layout.preferredWidth: 68 }
                            // 0 = auto (a standard SDR screen); brighter screens look better with a higher target
                            Slim { Layout.fillWidth: true; from: 0; to: 600; stepSize: 50; value: win.st.hdrPeak || 0
                                onMoved: Player.setHdr("tonemap", value < 100 ? 0 : value, win.st.hdrScene !== false) }
                            Text { text: (win.st.hdrPeak || 0) ? win.st.hdrPeak + " nits" : "Auto"; color: Theme.text; font.family: Theme.mono; font.pixelSize: 11
                                Layout.preferredWidth: 62; horizontalAlignment: Text.AlignRight }
                        }
                        Toggle { visible: win.st.hdrMode !== "display"; Layout.fillWidth: true; text: "Adapt to each scene"; hint: "Keeps dark scenes detailed and bright ones from clipping"
                            checked: win.st.hdrScene !== false; onToggled: Player.setHdr("tonemap", win.st.hdrPeak || 0, checked) }
                        Text { visible: win.st.hdrMode === "display"; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 11
                            text: "Turn on \u201CUse HDR\u201D in Windows display settings. Starts with the next video if this one began in the other mode." }
                    }
                    Text { visible: win.st.hdrOk !== true; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: 12
                        text: "HDR options need the MPV engine (Settings \u203A Playback). VLC adjusts HDR on its own." }
                    Head { text: "CREDITS" }
                    Toggle { Layout.fillWidth: true; text: "Next episode when the credits start"
                        hint: win.st.hasCredits ? "Credits found for this title. O marks them by hand." : "Press O where the credits start; it is remembered for the series."
                        checked: Backend.setting("auto_credits") !== "0"; onToggled: Backend.setSetting("auto_credits", checked ? "1" : "0") }
                }
            }
            }
        }

        // ---------------------------------------------------------------- snapshot menu (box art / fanart)
        Rectangle {
            id: snapMenu
            property real shown: root.popup === "camera" && bar.visible ? 1 : 0
            Behavior on shown { NumberAnimation { duration: (snapMenu.shown < 0.5 ? 260 : 180) * Theme.motion; easing.type: Easing.OutCubic } }
            visible: shown > 0.01
            width: 260
            height: snapCol.implicitHeight + 20
            x: Math.max(16, Math.min(root.anchorRight - width, parent.width - width - 16))
            y: bar.y - height - 12
            radius: 14
            color: Theme.panel
            border.color: Theme.edge
            opacity: Math.min(1, shown * 1.6)
            transform: Scale { origin.x: root.originX - snapMenu.x; origin.y: root.originY - snapMenu.y; xScale: 0.08 + 0.92 * snapMenu.shown; yScale: xScale }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (w) => w.accepted = true }
            ColumnLayout {
                id: snapCol
                x: 10; y: 10; width: parent.width - 20
                spacing: 2
                Head { text: "SNAPSHOT"; Layout.topMargin: 0; leftPadding: 10 }
                Row2 { label: "Use frame as box art (2:3)"; onPicked: { Player.captureFrame("poster"); root.popup = "" } }
                Row2 { label: "Use frame as fanart (16:9)"; onPicked: { Player.captureFrame("fanart"); root.popup = "" } }
            }
        }

        // ---------------------------------------------------------------- skip credits (films: ends playback, counts as watched)
        Rectangle {
            id: creditsBadge
            width: creditsRow.implicitWidth + 40; height: 48; radius: 12
            color: Theme.hud; border.color: Theme.edge
            visible: !root.pip
            y: parent.height - height - (root.controlsOn ? bar.height + bar.anchors.margins + 20 : 60)
            x: win.st.creditsActive === true ? parent.width - width - 40 : parent.width + 20
            Behavior on x { NumberAnimation { duration: 280 * Theme.motion; easing.type: Easing.OutCubic } }
            Behavior on y { NumberAnimation { duration: 200 * Theme.motion; easing.type: Easing.OutCubic } }
            Row {
                id: creditsRow; anchors.centerIn: parent; spacing: 10
                Text { text: "Skip Credits"; color: Theme.text; font.pixelSize: 15; font.weight: Font.Bold }
                Rectangle { width: tabKey2.implicitWidth + 12; height: 20; radius: 5; color: Theme.lineStrong; anchors.verticalCenter: parent.verticalCenter
                    Text { id: tabKey2; anchors.centerIn: parent; text: "TAB"; color: Theme.dim; font.family: Theme.mono; font.pixelSize: 10 } }
            }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Player.finishNow() }
        }

        // ---------------------------------------------------------------- picture in picture: compact controls, drag to move
        Item {
            id: pipLayer
            anchors.fill: parent
            visible: root.pip
            MouseArea {
                id: pipDrag
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                property point last
                property bool moved: false
                onPressed: (m) => { last = mapToGlobal(m.x, m.y); moved = false }
                onPositionChanged: (m) => {
                    root.poke()
                    if (!pressed) return
                    var g = mapToGlobal(m.x, m.y)
                    if (Math.abs(g.x - last.x) + Math.abs(g.y - last.y) > 2) moved = true
                    Player.movePip(Math.round(g.x - last.x), Math.round(g.y - last.y))
                    last = g
                }
                onClicked: if (!moved) Player.togglePause()
                onDoubleClicked: Player.togglePip()
                onWheel: (w) => { root.wheelAcc += w.angleDelta.y; var n = root.wheelAcc > 0 ? Math.floor(root.wheelAcc / 120) : Math.ceil(root.wheelAcc / 120)
                    if (n !== 0) { root.wheelAcc -= n * 120; root.setVol(root.vol + n * 5) } }
            }
            Rectangle {      // controls fade in on hover
                anchors.fill: parent
                opacity: pipDrag.containsMouse || win.st.paused ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 180 * Theme.motion } }
                gradient: Gradient {
                    GradientStop { position: 0; color: "#99000000" }
                    GradientStop { position: 0.4; color: "transparent" }
                    GradientStop { position: 0.7; color: "transparent" }
                    GradientStop { position: 1; color: "#99000000" }
                }
                // Back: stop and return to the library. PiP: back to the theater.
                GlassButton { anchors { top: parent.top; left: parent.left; margins: 10 } small: true; label: "Back"; glyph: "\u2039"
                    tip: "Stop and go back to the library"; onClicked: Player.stop() }
                GlassButton { anchors { top: parent.top; right: parent.right; margins: 10 } small: true; iconKind: "pip"; implicitWidth: 38
                    tip: "Back to the full player (P)"; onClicked: Player.togglePip() }
                Row {
                    anchors.centerIn: parent
                    spacing: 10
                    GlassButton { anchors.verticalCenter: parent.verticalCenter; small: true; iconKind: "back"; implicitWidth: 40
                        tip: "Back 10 seconds"; onClicked: Player.seekBy(-10) }
                    GlassButton { anchors.verticalCenter: parent.verticalCenter; primary: true; label: win.st.paused ? "\u25B6" : "\u275A\u275A"; implicitWidth: 52
                        onClicked: Player.togglePause() }
                    GlassButton { anchors.verticalCenter: parent.verticalCenter; small: true; iconKind: "forward"; implicitWidth: 40
                        tip: (win.st.nextTitle || "") !== "" ? "Forward 10 seconds" : "Skip 10 seconds"; onClicked: Player.seekBy(10) }
                }
                Rectangle {      // progress
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12 }
                    height: 4; radius: 2; color: Theme.edge
                    Rectangle { width: parent.width * Math.min(1, (win.st.position || 0) / Math.max(1, win.st.duration || 1)); height: parent.height; radius: 2; color: Theme.green }
                }
            }
        }

        // ---------------------------------------------------------------- cast menu (AirPlay / Chromecast)
        Rectangle {
            id: castMenu
            property real shown: root.popup === "cast" && bar.visible ? 1 : 0
            Behavior on shown { NumberAnimation { duration: (castMenu.shown < 0.5 ? 260 : 180) * Theme.motion; easing.type: Easing.OutCubic } }
            visible: shown > 0.01
            width: 280
            height: castCol.implicitHeight + 20
            x: Math.max(16, Math.min(root.anchorRight - width, parent.width - width - 16))
            y: bar.y - height - 12
            radius: 14
            color: Theme.panel
            border.color: Theme.edge
            opacity: Math.min(1, shown * 1.6)
            transform: Scale { origin.x: root.originX - castMenu.x; origin.y: root.originY - castMenu.y; xScale: 0.08 + 0.92 * castMenu.shown; yScale: xScale }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (w) => w.accepted = true }
            ColumnLayout {
                id: castCol
                x: 10; y: 10; width: parent.width - 20
                spacing: 2
                Head { text: "PLAY ON"; Layout.topMargin: 0; leftPadding: 10 }
                Repeater { model: root.castList
                    Row2 { label: modelData.name + "  \u00B7  " + modelData.kind; onPicked: { root.popup = ""; Backend.castPlaying(modelData.id) } } }
                Text { visible: root.castList.length === 0; Layout.fillWidth: true; wrapMode: Text.Wrap; leftPadding: 10; rightPadding: 10; bottomPadding: 6
                    color: Theme.muted; font.pixelSize: 12; text: "Looking for AirPlay and Chromecast devices\u2026 (add-ons: Settings \u203A Streaming)" }
            }
        }

        // ---------------------------------------------------------------- volume pill
        // Drops from the top edge as a dot, widens into the volume with its percentage, and once the volume has
        // stopped changing for a moment it reverses: narrows to the dot and rises out of view.
        Item {
            id: volPill
            z: 60
            property real drop: 0          // 0 = above the screen, 1 = resting
            property real grow: 0          // 0 = dot, 1 = full pill
            readonly property bool active: drop > 0 || grow > 0
            function ping() { hideVol.stop(); idleVol.restart(); if (grow < 1 && !showVol.running) showVol.restart() }
            Timer { id: idleVol; interval: 900; onTriggered: { showVol.stop(); hideVol.restart() } }
            SequentialAnimation {
                id: showVol
                NumberAnimation { target: volPill; property: "drop"; to: 1; duration: 220 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.6 }
                NumberAnimation { target: volPill; property: "grow"; to: 1; duration: 320 * Theme.motion; easing.type: Easing.OutBack; easing.overshoot: 1.2 }
            }
            SequentialAnimation {
                id: hideVol
                NumberAnimation { target: volPill; property: "grow"; to: 0; duration: 240 * Theme.motion; easing.type: Easing.InOutCubic }
                NumberAnimation { target: volPill; property: "drop"; to: 0; duration: 200 * Theme.motion; easing.type: Easing.InCubic }
            }
            width: 12 + 228 * grow
            height: 12 + 28 * Math.min(1, grow)
            x: (parent.width - width) / 2
            y: -height - 6 + (height + 6 + 20) * drop
            visible: active
            Rectangle {
                anchors.fill: parent
                radius: height / 2
                // a bright dot that darkens into glass as it opens
                color: Qt.rgba(1 - 0.93 * Math.min(1, volPill.grow), 1 - 0.93 * Math.min(1, volPill.grow), 1 - 0.93 * Math.min(1, volPill.grow), 0.95)
                border.color: Qt.rgba(1, 1, 1, 0.18 * Math.min(1, volPill.grow))
            }
            Row {
                anchors.centerIn: parent
                spacing: 10
                opacity: Math.max(0, Math.min(1, (volPill.grow - 0.55) / 0.4))
                Speaker { level: root.vol; anchors.verticalCenter: parent.verticalCenter }
                Rectangle {
                    width: 140; height: 6; radius: 3; color: Theme.edge
                    anchors.verticalCenter: parent.verticalCenter
                    Rectangle { width: parent.width * root.vol / 100; height: parent.height; radius: 3; color: Theme.text
                        Behavior on width { NumberAnimation { duration: 120 * Theme.motion; easing.type: Easing.OutCubic } } }
                }
                Text { width: 38; text: root.vol + "%"; color: Theme.text; font.family: Theme.mono; font.pixelSize: 13; font.weight: Font.Bold
                    horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter }
            }
        }

        // ---------------------------------------------------------------- skip intro badge (slides in from the right)
        Rectangle {
            id: introBadge
            visible: !root.pip
            width: introRow.implicitWidth + 40; height: 48; radius: 12
            color: Theme.hud; border.color: Theme.edge
            y: parent.height - height - (root.controlsOn ? bar.height + bar.anchors.margins + 20 : 60)
            x: win.st.introActive === true ? parent.width - width - 40 : parent.width + 20
            Behavior on x { NumberAnimation { duration: 280 * Theme.motion; easing.type: Easing.OutCubic } }
            Behavior on y { NumberAnimation { duration: 200 * Theme.motion; easing.type: Easing.OutCubic } }
            Row {
                id: introRow; anchors.centerIn: parent; spacing: 10
                Text { text: "Skip Intro"; color: Theme.text; font.pixelSize: 15; font.weight: Font.Bold }
                Rectangle { width: tabKey.implicitWidth + 12; height: 20; radius: 5; color: Theme.lineStrong; anchors.verticalCenter: parent.verticalCenter
                    Text { id: tabKey; anchors.centerIn: parent; text: "TAB"; color: Theme.dim; font.family: Theme.mono; font.pixelSize: 10 } }
            }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Player.skipIntro() }
        }

        // ---------------------------------------------------------------- next episode: the picture shrinks into the corner
        Item {
            id: nextUp
            visible: root.shrunk
            readonly property real sc: Math.pow(2, -1.9 * (win.st.shrink || 0))
            width: win.width * sc; height: win.height * sc
            x: win.width - width - win.width * 0.02 * (win.st.shrink || 0)
            y: win.height - height - win.height * 0.03 * (win.st.shrink || 0)
            Canvas {
                id: ring
                anchors.centerIn: parent
                width: 84; height: 84
                property real frac: (win.st.autoplayLeft || 0) / 15
                onFracChanged: requestPaint()
                onPaint: {
                    var c = getContext("2d")
                    c.reset()
                    c.lineWidth = 6
                    c.strokeStyle = Theme.edge
                    c.beginPath(); c.arc(42, 42, 36, 0, Math.PI * 2); c.stroke()
                    c.strokeStyle = Theme.green
                    c.beginPath(); c.arc(42, 42, 36, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac); c.stroke()
                }
                Text { anchors.centerIn: parent; text: win.st.autoplayLeft || ""; color: Theme.text; font.pixelSize: 28; font.weight: Font.DemiBold }
            }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Player.nextNow() }
        }
        Column {
            visible: root.shrunk
            spacing: 4
            anchors { right: nextUp.left; rightMargin: 24; verticalCenter: nextUp.verticalCenter }
            Text { anchors.right: parent.right; text: "UP NEXT"; color: Theme.faint; font.family: Theme.mono; font.pixelSize: 11 }
            Text { anchors.right: parent.right; text: win.st.nextTitle || ""; color: Theme.text; font.pixelSize: 22; font.weight: Font.ExtraBold; font.letterSpacing: -0.4; elide: Text.ElideRight; width: Math.min(implicitWidth, win.width * 0.4) }
            Text { anchors.right: parent.right; text: "Press Enter to play now"; color: Theme.muted; font.pixelSize: 13 }
        }

        // ---------------------------------------------------------------- toast
        Rectangle {
            id: toast
            opacity: 0
            visible: opacity > 0
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 56 }
            width: Math.min(toastLabel.implicitWidth + 36, parent.width - 48); height: 40; radius: 12
            color: Theme.hud; border.color: Theme.edge
            Behavior on opacity { NumberAnimation { duration: 180 * Theme.motion } }
            Text { id: toastLabel; anchors.centerIn: parent; width: Math.min(implicitWidth, parent.width - 36); elide: Text.ElideRight; color: Theme.text; font.family: Theme.mono; font.pixelSize: 12 }
            Timer { id: toastHide; interval: 2200; onTriggered: toast.opacity = 0 }
        }

        // ---------------------------------------------------------------- crop canvas for box art / fanart
        Rectangle {
            anchors.fill: parent
            color: "#EE000000"
            visible: root.cropping
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }   // swallow clicks
            Item {
                id: stage
                anchors { fill: parent; topMargin: 70; bottomMargin: 120; leftMargin: 80; rightMargin: 80 }
                Image {
                    id: shot
                    anchors.fill: parent
                    fillMode: Image.PreserveAspectFit
                    cache: false
                    source: (win.st.snapId || 0) > 0 ? "image://frames/snap?" + win.st.snapId : ""
                    onStatusChanged: if (status === Image.Ready) cropBox.reset()
                }
                Item {
                    id: frame
                    anchors.centerIn: shot
                    width: shot.paintedWidth; height: shot.paintedHeight
                    Rectangle {
                        id: cropBox
                        readonly property real ratio: win.st.snapshot === "poster" ? 2 / 3 : 16 / 9
                        height: Math.min(frame.height, frame.width / ratio) * zoom.value
                        width: height * ratio
                        color: Qt.rgba(Qt.color(Theme.blue).r, Qt.color(Theme.blue).g, Qt.color(Theme.blue).b, 0.1); border.color: Theme.blue; border.width: 2
                        function reset() { x = (frame.width - width) / 2; y = (frame.height - height) / 2 }
                        onWidthChanged: { x = Math.max(0, Math.min(x, frame.width - width)); y = Math.max(0, Math.min(y, frame.height - height)) }
                        MouseArea {
                            anchors.fill: parent; cursorShape: Qt.SizeAllCursor
                            drag.target: cropBox; drag.minimumX: 0; drag.maximumX: frame.width - cropBox.width
                            drag.minimumY: 0; drag.maximumY: frame.height - cropBox.height
                        }
                    }
                }
            }
            RowLayout {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 32 }
                spacing: 16
                Text { text: win.st.snapshot === "poster" ? "Box art (2:3)" : "Fanart (16:9)"; color: Theme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                Text { text: "Size"; color: Theme.muted; font.pixelSize: 13 }
                Slider { id: zoom; from: 0.3; to: 1.0; value: 1.0; Layout.preferredWidth: 220 }
                Item { Layout.fillWidth: true }
                GlassButton { label: "Cancel"; onClicked: Player.cancelSnapshot() }
                GlassButton {
                    label: "Save"; primary: true
                    onClicked: Player.saveSnapshot(win.st.snapshot, cropBox.x / frame.width, cropBox.y / frame.height,
                                                   cropBox.width / frame.width, cropBox.height / frame.height)
                }
            }
        }
    }
}
