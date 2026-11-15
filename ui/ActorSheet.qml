// Add an actor to one title or many at once: pick someone already in your library (suggestions as you type) or type
// a new name, give their part, and choose a photo. The photo is theirs everywhere: every title they are in shows it.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects

Sheet {
    id: root
    maxWidth: 520
    maxHeight: 600
    scrolls: false
    property var keys: []
    property var found: []
    property string photo: ""          // a picture you chose (file:/// URL), or the picked actor's own
    property bool ownPhoto: false      // the photo above is a file you chose just now
    title: "Add an actor"
    sub: keys.length > 1 ? "To all " + keys.length + " selected titles. Anyone already in a cast is skipped there."
                         : "To this title's cast."
    signal added()

    function begin(k, source) {
        keys = k; nameField.text = ""; roleField.text = ""; photo = ""; ownPhoto = false; found = Backend.people("")
        open(source)
        nameField.forceActiveFocus()
    }
    function pick(p) {
        nameField.text = p.name
        if (!ownPhoto) photo = p.photo
        found = []
        roleField.forceActiveFocus()
    }
    function commit() {
        if (nameField.text.trim() === "") return
        if (Backend.addActor(keys, nameField.text, roleField.text, ownPhoto ? photo : "") >= 0) { added(); close() }
    }
    readonly property bool known: found.some(function(p) { return p.name.toLowerCase() === nameField.text.trim().toLowerCase() })

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            // the photo: tap to choose one
            Rectangle {
                id: face
                Layout.preferredWidth: 84; Layout.preferredHeight: 84
                radius: 42
                color: Theme.slate
                border.color: faceHover.hovered ? Theme.blue : Theme.line
                border.width: faceHover.hovered ? 2 : 1
                scale: faceTap.pressed ? 0.96 : 1
                Behavior on scale { NumberAnimation { duration: 120 * Theme.motion; easing.type: Easing.OutCubic } }
                Behavior on border.color { ColorAnimation { duration: 140 * Theme.motion } }
                Image {
                    id: faceImg
                    anchors.fill: parent; anchors.margins: 2
                    source: root.photo; visible: root.photo !== ""
                    fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 168; sourceSize.height: 168
                    layer.enabled: visible                   // a file you chose is square: shown round, as it is saved
                    layer.effect: MultiEffect { maskEnabled: true; maskSource: faceMask }
                    opacity: status === Image.Ready ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 200 * Theme.motion } }
                }
                Item { id: faceMask; anchors.fill: faceImg; layer.enabled: true; visible: false
                    Rectangle { anchors.fill: parent; radius: width / 2 } }
                Column {
                    anchors.centerIn: parent
                    visible: root.photo === ""
                    spacing: 2
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "+"; color: Theme.muted; font.pixelSize: 22 }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Photo"; color: Theme.faint; font.pixelSize: 10 }
                }
                HoverHandler { id: faceHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { id: faceTap; onTapped: { var u = Backend.pickActorPhoto(); if (u !== "") { root.photo = u; root.ownPhoto = true } } }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8
                Field {
                    id: nameField
                    Layout.fillWidth: true
                    placeholderText: "Name"
                    onTextEdited: root.found = Backend.people(text)
                    onAccepted: root.found.length && !root.known ? root.pick(root.found[0]) : roleField.forceActiveFocus()
                    Keys.onDownPressed: if (root.found.length) suggestions.forceActiveFocus()
                }
                Field { id: roleField; Layout.fillWidth: true; placeholderText: "Part (optional)"; onAccepted: root.commit() }
            }
        }

        Text {
            text: nameField.text.trim() === "" ? "IN YOUR LIBRARY" : root.known ? "IN YOUR LIBRARY" : root.found.length ? "MATCHES" : ""
            color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10
        }
        ListView {
            id: suggestions
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: root.found
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: true
            Keys.onReturnPressed: if (currentIndex >= 0) root.pick(root.found[currentIndex])
            delegate: Rectangle {
                id: sug
                required property var modelData
                required property int index
                width: ListView.view.width; height: 44; radius: 9
                color: sugHover.hovered || (suggestions.activeFocus && ListView.isCurrentItem) ? Theme.fillHover : "transparent"
                Rectangle {
                    id: mini
                    x: 8; anchors.verticalCenter: parent.verticalCenter
                    width: 30; height: 30; radius: 15; color: Theme.slate; border.color: Theme.line
                    Image { anchors.fill: parent; source: sug.modelData.photo; visible: sug.modelData.photo !== ""
                        fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 60; sourceSize.height: 60 }
                    Text { visible: sug.modelData.photo === ""; anchors.centerIn: parent; color: "#B3FFFFFF"; font.pixelSize: 11; font.weight: Font.Bold
                        text: sug.modelData.name.split(" ").filter(function(w) { return w.length }).slice(0, 2).map(function(w) { return w[0] }).join("") }
                }
                Text { anchors { left: mini.right; leftMargin: 10; right: n.left; rightMargin: 10; verticalCenter: parent.verticalCenter }
                    text: sug.modelData.name; color: Theme.text; font.pixelSize: 13; elide: Text.ElideRight }
                Text { id: n; anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                    text: sug.modelData.titles === 0 ? "added by you" : sug.modelData.titles === 1 ? "1 title" : sug.modelData.titles + " titles"
                    color: Theme.faint; font.family: Theme.mono; font.pixelSize: 10 }
                HoverHandler { id: sugHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.pick(sug.modelData) }
            }
            Text { anchors.centerIn: parent; visible: root.found.length === 0 && nameField.text.trim() !== ""
                text: "New actor: “" + nameField.text.trim() + "”"; color: Theme.faint; font.pixelSize: 12 }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.faint; font.pixelSize: 11
                text: root.ownPhoto ? "This photo will show for them on every title." : "Tap the circle to choose a photo." }
            GlassButton { small: true; label: "Cancel"; onClicked: root.close() }
            GlassButton { small: true; primary: true; enabled: nameField.text.trim() !== ""; opacity: enabled ? 1 : 0.4
                label: root.keys.length > 1 ? "Add to " + root.keys.length + " titles" : "Add"; onClicked: root.commit() }
        }
    }
}
