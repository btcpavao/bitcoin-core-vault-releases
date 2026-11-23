#!/usr/bin/python3
"""Compile actual native Review/editor UI fragments against Qt, with no disk jobs.

The fake core supplies synthetic reviewed plans; policy tests separately validate
those plans. Dialog controls, their validation callbacks, sizing and Review text
come directly from the shipping source templates, rather than a second UI copy.
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


def between(text, start, end):
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError('Native UI fixture anchors changed; please review the test.')
    return text[text.index(start):text.index(end)]


def run(product, branding, artifacts):
    root = Path(__file__).resolve().parent
    qt = next((name for name in ('Qt6Widgets', 'Qt5Widgets')
               if subprocess.run(['pkg-config', '--exists', name]).returncode == 0), None)
    if qt is None:
        raise RuntimeError('Qt Widgets development files are required.')
    source = (root / 'shared/PartitionPage.cpp').read_text()
    helper = between(source, 'static void preparePartitionDialog(', 'static bool espCandidate(')
    edit = between(source, '    QDialog dialog(this); dialog.setObjectName(QStringLiteral("corePartitionEditDialog"))',
                   '    if(dialog.exec()==QDialog::Accepted && format->isChecked()) setRoot(p);')
    create = between(source, '    QDialog dialog(this); dialog.setObjectName(QStringLiteral("coreCreateLayoutDialog"))',
                     '    if(dialog.exec()!=QDialog::Accepted) return;')
    review = (root / 'shared/Review.cpp.inc').read_text()
    code = r'''
#include <QApplication>
#include <QDialog>
#include <QFormLayout>
#include <QScreen>
#include <QCheckBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QLabel>
#include <QPushButton>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QRadioButton>
#include <QStyleOptionButton>
#include <QFile>
#include <QVariant>
#include <QtMath>
#include <QJsonArray>
#include <QJsonObject>
#include <iostream>
#include <stdexcept>
static constexpr qint64 GiB=1024LL*1024*1024;
static constexpr bool isNode=CORE_PRODUCT_NODE;
static const int rootMinimum=isNode?32:16;
static const int companionMinimum=isNode?16:32;
static const char* companionName=isNode?"Vault":"Node";
static QString sizeText(qint64 n) {return QString::number(double(n)/GiB,'f',2)+" GiB";}
static void require(bool value,const char* message) {if(!value) throw std::runtime_error(message);}
static QString outputDirectory;
static QString productName;
static QSize testScreen;
static void capture(QWidget& widget,const QString& name) {
    if(!outputDirectory.isEmpty()) require(widget.grab().save(outputDirectory+"/"+productName+"-"+name+"-"+
        QString::number(testScreen.width())+"x"+QString::number(testScreen.height())+".png"),"Cannot save UI evidence");
}
UI_DIALOG_HELPER
static void checkEditor(QDialog& dialog,QFormLayout& form) {
    dialog.show(); QApplication::processEvents();
    require(dialog.minimumSize()==dialog.maximumSize(),"Editor lacks fixed window-manager size hints");
    require(!dialog.windowFlags().testFlag(Qt::WindowMaximizeButtonHint),"Editor offers maximize");
    require(dialog.width()<=560 && dialog.height()<500,"Editor is not compact");
    require(dialog.parentWidget()->window()->frameGeometry().contains(dialog.frameGeometry()),"Editor is outside its parent");
    require(form.totalHeightForWidth(dialog.width())<=dialog.height(),"Wrapped editor content is clipped");
    for(auto* child:dialog.findChildren<QWidget*>()) {
        if(!child->isVisible() || child->isWindow()) continue;
        const QRect area(child->mapTo(&dialog,QPoint()),child->size());
        require(dialog.rect().contains(area),"Editor control extends beyond the dialog");
    }
    for(auto* spin:dialog.findChildren<QDoubleSpinBox*>()) {
        QStyleOptionSpinBox option; option.initFrom(spin); option.buttonSymbols=QAbstractSpinBox::UpDownArrows;
        const QRect up=spin->style()->subControlRect(QStyle::CC_SpinBox,&option,QStyle::SC_SpinBoxUp,spin).adjusted(3,3,-3,-3);
        const auto pixels=spin->grab().toImage(); int visible=0;
        for(int y=up.top();y<=up.bottom();++y) for(int x=up.left();x<=up.right();++x)
            if(qGray(pixels.pixel(x,y))>160) ++visible;
        require(visible>5,"Numeric spinner arrow is invisible");
    }
}
struct FakePartition {
    QString partitionPath() const {return "/dev/vda3";}
    qint64 capacity() const {return 60*GiB;}
};
class EditorProbe:public QWidget {
public:
    void checkEdit() {
        FakePartition partition; auto* p=&partition;
UI_EDIT_BODY
        require(!buttons->button(QDialogButtonBox::Ok)->isEnabled(),"Format consent was not required");
        format->setChecked(true);
        require(buttons->button(QDialogButtonBox::Ok)->isEnabled(),"Format consent does not enable confirmation");
        checkEditor(dialog,*form); capture(dialog,"edit"); dialog.close();
    }
    void checkCreate() {
        const qint64 availableMiB=96767; const bool hasEsp=true;
UI_CREATE_BODY
        require(!other->isEnabled(),"Reservation starts enabled without consent");
        reserve->setChecked(true); other->setValue(32); root->setValue(60);
        require(other->isEnabled() && buttons->button(QDialogButtonBox::Ok)->isEnabled(),"Valid 60+32 GiB layout is rejected");
        root->setValue(94);
        require(!buttons->button(QDialogButtonBox::Ok)->isEnabled(),"Oversized layout can be confirmed");
        root->setValue(60);
        checkEditor(dialog,*form); capture(dialog,"create"); dialog.close();
    }
};
struct FakeCore {
    QJsonObject plan; QString error;
    QJsonObject installPlan(const void*) const {return plan;}
    QString validateInstallPlan(const void*) const {return error;}
};
class ReviewProbe:public QWidget {
public:
    FakeCore* m_core; const void* m_config=nullptr;
    QWidget* render() const {
UI_REVIEW_BODY
    }
};
static QJsonObject partition(const QString& path,const QString& mount,bool fresh,bool format,double size,const QString& label=QString()) {
    return {{"path",path},{"mount",mount},{"new",fresh},{"format",format},{"size",size*GiB},{"label",label}};
}
static QString reviewText(FakeCore& core) {
    ReviewProbe probe; probe.m_core=&core; QWidget* rendered=probe.render(); QString result;
    for(auto* label:rendered->findChildren<QLabel*>()) result+=label->text()+"\n";
    delete rendered; return result;
}
static void checkReview() {
    FakeCore core;
    core.plan={{"target","/dev/vda"},{"mode","erase"},
        {"expected",QJsonObject{{"model","QEMU <fixture>"},{"size",64.0*GiB}}}};
    for(bool efi:{false,true}) {
        QJsonArray parts;
        if(efi) parts.append(partition("/dev/vda1","/boot/efi",true,true,.5));
        if(isNode) parts.append(partition("/dev/vda2","/boot",true,true,1));
        parts.append(partition("/dev/vda3","/",true,true,60));
        core.plan["disks"]=QJsonArray{QJsonObject{{"path","/dev/vda"},{"partitions",parts}}};
        const auto text=reviewText(core);
        require(text.contains("QEMU &lt;fixture&gt;"),"Drive identity is not HTML escaped");
        require(text.contains("Create and format ext4 boot partition")==isNode,"Automatic boot action is missing or spurious");
        require(!text.contains("unformatted reservation"),"Automatic /boot is described as a reservation");
        require(text.contains("Create EFI / FAT32")==efi,"Automatic EFI action is inaccurate");
        require(text.contains("Format ext4; install Bitcoin Core"),"Root formatting action missing");
    }
    core.plan["mode"]="advanced";
    core.plan["disks"]=QJsonArray{QJsonObject{{"path","/dev/vda"},{"partitions",QJsonArray{
        partition("/dev/vda1","/boot/efi",false,false,.5),
        partition("/dev/vda2","",false,false,1),
        partition("/dev/vda3","/",true,true,60),
        partition("/dev/vda4","",true,false,32,"companion-reserved")}}}};
    const auto advanced=reviewText(core);
    require(advanced.contains("Reuse EFI; do not format") && advanced.contains("Keep unchanged"),"Preservation is not explicit");
    require(advanced.count("unformatted reservation")==1 && !advanced.contains("ext4 boot partition"),"Advanced reservation action is inaccurate");
    require(advanced.contains(isNode?"reservation for Vault":"reservation for Node"),"Companion product is mislabeled");
    core.error="Synthetic rejected plan";
    const auto blocked=reviewText(core);
    require(blocked.contains(core.error) && !blocked.contains("<table"),"Rejected plan displays an actionable operation table");
    require(!QCoreApplication::instance()->property("coreInstallPlanValid").toBool(),"Rejected plan permits confirmation");
}
static void checkChoices() {
    QWidget choice; choice.setObjectName("coreInstallMethodErase"); auto* row=new QHBoxLayout(&choice);
    auto* radio=new QRadioButton(&choice); row->addWidget(radio);
    row->addWidget(new QLabel("<strong>Install to disk</strong><br/>Erase the selected physical disk.",&choice));
    choice.show(); QApplication::processEvents();
    QStyleOptionButton option; option.initFrom(radio);
    const QRect indicator=radio->style()->subElementRect(QStyle::SE_RadioButtonIndicator,&option,radio);
    require(indicator.width()>=20 && indicator.height()>=20,"Method indicator is too small");
    const auto unchecked=radio->grab().toImage();
    int visible=0;
    for(int y=indicator.top();y<=indicator.bottom();++y) for(int x=indicator.left();x<=indicator.right();++x)
        if(qGray(unchecked.pixel(x,y))>120) ++visible;
    require(visible>30,"Unchecked method outline is invisible");
    radio->setChecked(true); QApplication::processEvents();
    const auto checked=radio->grab().toImage();
    require(qGray(checked.pixel(indicator.center()))>200,"Checked method lacks a visible center");
    require(unchecked!=checked,"Checked and unchecked methods look identical");
    capture(choice,"method");
}
int main(int argc,char** argv) {
    QApplication app(argc,argv); require(argc==3,"Style and output directory are required");
    QFile style(QString::fromLocal8Bit(argv[1])); require(style.open(QIODevice::ReadOnly),"Missing stylesheet");
    app.setStyleSheet(QString::fromUtf8(style.readAll()));
    outputDirectory=QString::fromLocal8Bit(argv[2]); productName=isNode?"node":"vault";
    checkReview();
    for(const QSize size:{QSize(800,600),QSize(1280,800)}) {
        testScreen=size; EditorProbe parent; parent.resize(size); parent.show(); QApplication::processEvents();
        parent.checkCreate(); parent.checkEdit(); parent.close();
        std::cout<<"PASS actual native editor controls/geometry "<<size.width()<<"x"<<size.height()<<std::endl;
    }
    checkChoices(); std::cout<<"PASS native Review boot/EFI/root/reservation semantics and visible method indicators"<<std::endl;
}
'''
    for name, fragment in (('UI_DIALOG_HELPER', helper), ('UI_EDIT_BODY', edit),
                           ('UI_CREATE_BODY', create), ('UI_REVIEW_BODY', review)):
        code = code.replace(name, fragment)
    code = code.replace('CORE_PRODUCT_NODE', 'true' if product == 'node' else 'false')
    if product == 'node':
        code = code.replace('Bitcoin Core Vault', 'Bitcoin Core Node')
    style = (branding / 'stylesheet.qss').read_text()
    for name in ('core-node', 'core-offline'):
        style = style.replace('/etc/calamares/branding/' + name + '/', str(branding) + '/')
    if artifacts:
        artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='core-native-ui-test-') as directory:
        work = Path(directory)
        (work / 'test.cpp').write_text(code)
        (work / 'stylesheet.qss').write_text(style)
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', qt], text=True))
        subprocess.run(['g++', '-std=c++17', '-fPIC', str(work / 'test.cpp'), '-o', str(work / 'test'), *flags], check=True)
        subprocess.run([str(work / 'test'), str(work / 'stylesheet.qss'), str(artifacts) if artifacts else ''],
                       check=True, timeout=35, env=dict(os.environ, QT_QPA_PLATFORM='offscreen',
                       QT_SCALE_FACTOR='1', QT_AUTO_SCREEN_SCALE_FACTOR='0'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', choices=('node', 'vault'), required=True)
    parser.add_argument('--branding', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    run(args.product, args.branding.resolve(), args.artifacts.resolve() if args.artifacts else None)
