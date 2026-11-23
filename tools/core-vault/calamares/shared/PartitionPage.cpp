// SPDX-License-Identifier: GPL-3.0-or-later
#include "PartitionPage.h"
#include "Config.h"
#include "core/DeviceModel.h"
#include "core/KPMHelpers.h"
#include "core/PartUtils.h"
#include "core/PartitionCoreModule.h"
#include "core/PartitionInfo.h"
#include "partition/PartitionIterator.h"
#include "partition/PartitionQuery.h"
#include <kpmcore/core/device.h>
#include <kpmcore/core/partition.h>
#include <kpmcore/core/partitiontable.h>
#include <QCheckBox>
#include <QComboBox>
#include <QCoreApplication>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHeaderView>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QSignalBlocker>
#include <QTreeWidget>
#include <QVBoxLayout>
#include <QtMath>

using Calamares::Partition::PartitionIterator;
using Calamares::Partition::isPartitionFreeSpace;
using Calamares::Partition::isPartitionNew;
static constexpr qint64 MiB = 1024LL * 1024;
static constexpr qint64 GiB = 1024LL * MiB;
static constexpr bool isNode = CORE_PRODUCT_NODE;
static const int rootMinimum = isNode ? 32 : 16;
static const int companionMinimum = isNode ? 16 : 32;
static const char* companionName = isNode ? "Vault" : "Node";
static const char* companionLabel = isNode ? "BitcoinCoreVaultReserved" : "BitcoinCoreNodeReserved";
static QString sizeText(qint64 n) { return QString::number(double(n)/GiB, 'f', 2)+QStringLiteral(" GiB"); }
static bool espCandidate(const Partition* p)
{
    return p && !isPartitionFreeSpace(p) && !isPartitionNew(p)
        && p->fileSystem().type() == FileSystem::Type::Fat32
        && p->capacity() >= 128*MiB && PartUtils::isEfiBootable(p);
}

PartitionPage::PartitionPage(PartitionCoreModule* core, const Config& config, QWidget* parent)
    : QWidget(parent), m_core(core), m_config(config)
{
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0,0,0,0); layout->setSpacing(12);
    auto* title = new QLabel(tr("Advanced partitioning"), this);
    title->setObjectName(QStringLiteral("coreOfflinePageTitle"));
    title->setAlignment(Qt::AlignCenter); layout->addWidget(title);
    auto* subtitle = new QLabel(tr("Choose an existing partition, or create a layout in unallocated space. No changes are written until you confirm Review."), this);
    subtitle->setObjectName(QStringLiteral("coreOfflinePageDescription"));
    subtitle->setAlignment(Qt::AlignCenter); subtitle->setWordWrap(true); layout->addWidget(subtitle);
    auto* row = new QHBoxLayout;
    row->addWidget(new QLabel(tr("Installation drive:"),this));
    m_drive = new QComboBox(this); m_drive->setModel(core->deviceModel()); row->addWidget(m_drive,1);
    layout->addLayout(row);
    m_table = new QTreeWidget(this);
    m_table->setHeaderLabels({tr("Partition"),tr("Size"),tr("Filesystem"),tr("Mount point"),tr("Format")});
    m_table->setRootIsDecorated(false); m_table->setSelectionMode(QAbstractItemView::SingleSelection);
    m_table->setMinimumHeight(150); m_table->header()->setSectionResizeMode(QHeaderView::ResizeToContents);
    m_table->header()->setSectionResizeMode(0,QHeaderView::Stretch); layout->addWidget(m_table,1);
    auto* buttons = new QHBoxLayout;
    m_create = new QPushButton(tr("Create layout…"),this);
    m_edit = new QPushButton(tr("Edit…"),this);
    m_erase = new QPushButton(tr("Erase selected disk…"),this);
    auto* revert = new QPushButton(tr("Revert changes"),this);
    buttons->addWidget(m_create); buttons->addWidget(m_edit); buttons->addStretch();
    buttons->addWidget(m_erase); buttons->addWidget(revert); layout->addLayout(buttons);
    m_status = new QLabel(this); m_status->setWordWrap(true);
    m_status->setObjectName(QStringLiteral("coreOfflineEraseWarning")); layout->addWidget(m_status);
    connect(m_create,&QPushButton::clicked,this,&PartitionPage::createLayout);
    connect(m_edit,&QPushButton::clicked,this,&PartitionPage::edit);
    connect(m_erase,&QPushButton::clicked,this,&PartitionPage::eraseDisk);
    connect(revert,&QPushButton::clicked,this,&PartitionPage::onRevertClicked);
    connect(m_table,&QTreeWidget::itemDoubleClicked,this,[this] { edit(); });
    connect(m_table,&QTreeWidget::itemSelectionChanged,this,[this] {
        auto* p=selection(); const bool enabled=PartUtils::isEfiSystem() && device();
        m_create->setEnabled(enabled && p && isPartitionFreeSpace(p) && !m_core->hasRootMountPoint());
        m_edit->setEnabled(enabled && p && !isPartitionFreeSpace(p) && !isPartitionNew(p));
    });
    connect(m_drive,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int) {
        if(m_busy) return;
        // A different disk is not allowed to retain any queued operations.
        m_busy=true; m_core->revertAllDevices();
        QCoreApplication::instance()->setProperty("coreInstallEraseDisk",QString());
        m_busy=false; refresh();
    });
    refresh();
}
Device* PartitionPage::device() const
{
    return m_core->deviceModel()->deviceForIndex(m_core->deviceModel()->index(m_drive->currentIndex(),0));
}
Partition* PartitionPage::selection() const
{
    auto* item=m_table->currentItem();
    return item ? reinterpret_cast<Partition*>(item->data(0,Qt::UserRole).value<quintptr>()) : nullptr;
}
int PartitionPage::selectedDeviceIndex() { return m_drive->currentIndex(); }
void PartitionPage::selectDeviceByIndex(int n)
{
    const QSignalBlocker block(m_drive); m_drive->setCurrentIndex(n); refresh();
}
void PartitionPage::onRevertClicked()
{
    m_busy=true; m_core->revertAllDevices(); m_busy=false;
    QCoreApplication::instance()->setProperty("coreInstallEraseDisk",QString()); refresh();
}
void PartitionPage::refresh()
{
    m_table->clear(); auto* d=device();
    m_create->setEnabled(false); m_edit->setEnabled(false);
    m_erase->setEnabled(d && PartUtils::isEfiSystem());
    if(!d) { m_status->setText(tr("No eligible internal drive is available.")); return; }
    m_core->setBootLoaderInstallPath(d->deviceNode());
    if(d->partitionTable()) for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it) {
        auto* p=*it; const bool free=isPartitionFreeSpace(p);
        QString name=free ? tr("Unallocated space") : p->partitionPath();
        if(name.isEmpty()) name=tr("New partition");
        if(!free && !p->label().isEmpty()) name += QStringLiteral(" — ")+p->label();
        auto* item=new QTreeWidgetItem(m_table,{name,sizeText(p->capacity()),
            free ? QStringLiteral("—") : FileSystem::nameForType(p->fileSystem().type()),
            PartitionInfo::mountPoint(p),PartitionInfo::format(p) ? tr("Yes") : tr("No")});
        item->setData(0,Qt::UserRole,QVariant::fromValue<quintptr>(reinterpret_cast<quintptr>(p)));
    }
    if(!PartUtils::isEfiSystem()) {
        m_status->setText(tr("Advanced partitioning requires UEFI mode. Restart this USB in UEFI mode, or go Back and use Install to disk for a whole-disk BIOS installation.")); return;
    }
    if(!d->partitionTable() || d->partitionTable()->type()!=PartitionTable::gpt) {
        m_status->setText(tr("Advanced preservation requires a GPT disk. To replace this disk completely, choose Erase selected disk. No existing partition is resized.")); return;
    }
    if(m_core->hasRootMountPoint()) {
        auto error=m_core->validateInstallPlan(&m_config);
        m_status->setText(error.isEmpty() ? tr("The selected root will be formatted as ext4. The existing EFI partition is reused without formatting; every other existing partition and physical disk is preserved. Review shows the exact operations.") : error);
    } else m_status->setText(tr("Select a partition and choose Edit to install there. Select unallocated space and choose Create layout to optionally reserve space for %1. Existing partitions are never shrunk or moved.").arg(QString::fromLatin1(companionName)));
}
bool PartitionPage::assignEsp()
{
    auto* d=device(); if(!d || !d->partitionTable()) return false;
    QList<Partition*> candidates;
    for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it) {
        if(PartitionInfo::mountPoint(*it)==QStringLiteral("/boot/efi")) return true;
        if(espCandidate(*it)) candidates.append(*it);
    }
    if(candidates.size()!=1) return false;
    PartitionInfo::setMountPoint(candidates.first(),QStringLiteral("/boot/efi"));
    PartitionInfo::setFormat(candidates.first(),false);
    m_core->refreshPartition(d,candidates.first()); return true;
}
void PartitionPage::setRoot(Partition* p)
{
    auto* d=device(); if(!d || !p) return;
    if(p->fileSystem().type()==FileSystem::Type::Ext4) {
        PartitionInfo::setMountPoint(p,QStringLiteral("/")); PartitionInfo::setFormat(p,true);
        m_core->formatPartition(d,p);
    } else {
        auto* n=KPMHelpers::createNewPartition(p->parent(),*d,p->roles(),FileSystem::Type::Ext4,
            QString(),p->firstSector(),p->lastSector(),KPM_PARTITION_FLAG(None));
        n->setLabel(p->label());
        PartitionInfo::setMountPoint(n,QStringLiteral("/")); PartitionInfo::setFormat(n,true);
        m_core->deletePartition(d,p); m_core->createPartition(d,n);
    }
    assignEsp(); refresh();
}
void PartitionPage::edit()
{
    auto* p=selection(); auto* d=device();
    if(!PartUtils::isEfiSystem() || !d || !p || isPartitionFreeSpace(p) || isPartitionNew(p)) return;
    if(!d->partitionTable() || d->partitionTable()->type()!=PartitionTable::gpt) return;
    if(espCandidate(p)) {
        if(QMessageBox::question(this,tr("Use EFI partition"),tr("Use %1 at /boot/efi without formatting? Existing EFI files will be preserved.").arg(p->partitionPath()))!=QMessageBox::Yes) return;
        for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it)
            if(PartitionInfo::mountPoint(*it)==QStringLiteral("/boot/efi")) PartitionInfo::setMountPoint(*it,QString());
        PartitionInfo::setMountPoint(p,QStringLiteral("/boot/efi")); PartitionInfo::setFormat(p,false);
        m_core->refreshPartition(d,p); refresh(); return;
    }
    if(m_core->hasRootMountPoint()) { QMessageBox::information(this,tr("Root already selected"),tr("Choose Revert changes before selecting a different root partition.")); return; }
    if(p->capacity()<rootMinimum*GiB) { QMessageBox::warning(this,tr("Partition too small"),tr("The installation needs at least %1 GiB.").arg(rootMinimum)); return; }
    QDialog dialog(this); dialog.setWindowTitle(tr("Edit partition"));
    auto* form=new QFormLayout(&dialog);
    form->addRow(tr("Partition:"),new QLabel(p->partitionPath(),&dialog));
    form->addRow(tr("Size:"),new QLabel(sizeText(p->capacity()),&dialog));
    form->addRow(tr("Filesystem:"),new QLabel(QStringLiteral("ext4"),&dialog));
    form->addRow(tr("Mount point:"),new QLabel(QStringLiteral("/"),&dialog));
    auto* format=new QCheckBox(tr("Format this partition. Its current files will be erased."),&dialog); form->addRow(format);
    auto* buttons=new QDialogButtonBox(QDialogButtonBox::Ok|QDialogButtonBox::Cancel,&dialog); form->addRow(buttons);
    buttons->button(QDialogButtonBox::Ok)->setEnabled(false);
    connect(format,&QCheckBox::toggled,buttons->button(QDialogButtonBox::Ok),&QPushButton::setEnabled);
    connect(buttons,&QDialogButtonBox::accepted,&dialog,&QDialog::accept);
    connect(buttons,&QDialogButtonBox::rejected,&dialog,&QDialog::reject);
    if(dialog.exec()==QDialog::Accepted && format->isChecked()) setRoot(p);
}
void PartitionPage::createLayout()
{
    auto* free=selection(); auto* d=device();
    if(!PartUtils::isEfiSystem() || !d || !free || !isPartitionFreeSpace(free) || m_core->hasRootMountPoint()) return;
    if(!d->partitionTable() || d->partitionTable()->type()!=PartitionTable::gpt) return;
    bool hasEsp=false;
    for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it) if(espCandidate(*it)) hasEsp=true;
    const qint64 unit=MiB/d->logicalSize();
    const qint64 first=((free->firstSector()+unit-1)/unit)*unit;
    const qint64 end=((free->lastSector()+1)/unit)*unit;
    const qint64 availableMiB=(end-first)/unit-(hasEsp?0:512);
    if(availableMiB<rootMinimum*1024) { QMessageBox::warning(this,tr("Not enough unallocated space"),tr("This unallocated area is too small for root and EFI.")); return; }
    QDialog dialog(this); dialog.setWindowTitle(tr("Create layout")); auto* form=new QFormLayout(&dialog);
    auto* note=new QLabel(tr("Only this unallocated area is used. Existing partitions keep their boundaries and files."),&dialog); note->setWordWrap(true); form->addRow(note);
    auto* root=new QDoubleSpinBox(&dialog); root->setDecimals(2); root->setRange(rootMinimum,double(availableMiB)/1024); root->setSuffix(QStringLiteral(" GiB")); root->setValue(double(availableMiB)/1024);
    form->addRow(tr("Bitcoin Core Vault root:"),root);
    auto* reserve=new QCheckBox(tr("Reserve unformatted space for %1").arg(QString::fromLatin1(companionName)),&dialog); form->addRow(reserve);
    auto* other=new QDoubleSpinBox(&dialog); other->setDecimals(2); other->setRange(companionMinimum,qMax(double(companionMinimum),double(availableMiB)/1024-rootMinimum)); other->setSuffix(QStringLiteral(" GiB")); other->setEnabled(false); form->addRow(tr("Reserved size:"),other);
    auto* status=new QLabel(&dialog); status->setWordWrap(true); form->addRow(status);
    auto* buttons=new QDialogButtonBox(QDialogButtonBox::Ok|QDialogButtonBox::Cancel,&dialog); form->addRow(buttons);
    auto validate=[=] {
        qint64 r=qRound64(root->value()*1024), o=reserve->isChecked()?qRound64(other->value()*1024):0;
        bool ok=r>=rootMinimum*1024 && (!reserve->isChecked() || o>=companionMinimum*1024) && r+o<=availableMiB;
        buttons->button(QDialogButtonBox::Ok)->setEnabled(ok);
        status->setText(ok ? tr("EFI: %1. Remaining unallocated: %2 MiB.").arg(hasEsp?tr("reuse without formatting"):tr("create 512 MiB FAT32")).arg(availableMiB-r-o) : tr("Root and reserved space exceed this unallocated area."));
    };
    connect(reserve,&QCheckBox::toggled,&dialog,[=](bool checked) {
        other->setEnabled(checked);
        if(checked) {
            const double maxOther=double(availableMiB)/1024-rootMinimum;
            const double wanted=isNode ? qMin(32.0,maxOther) : qMax(double(companionMinimum),double(availableMiB)/1024-32.0);
            other->setValue(wanted); root->setValue(double(availableMiB)/1024-other->value());
        } else root->setValue(double(availableMiB)/1024);
        validate();
    });
    connect(root,QOverload<double>::of(&QDoubleSpinBox::valueChanged),&dialog,[=](double){validate();});
    connect(other,QOverload<double>::of(&QDoubleSpinBox::valueChanged),&dialog,[=](double){validate();});
    connect(buttons,&QDialogButtonBox::accepted,&dialog,&QDialog::accept); connect(buttons,&QDialogButtonBox::rejected,&dialog,&QDialog::reject); validate();
    if(dialog.exec()!=QDialog::Accepted) return;
    qint64 cursor=first;
    auto add=[&](qint64 mib,FileSystem::Type fs,const QString& mount,const QString& label,PartitionTable::Flags flags) {
        auto* p=KPMHelpers::createNewPartition(d->partitionTable(),*d,PartitionRole(PartitionRole::Primary),fs,QString(),cursor,cursor+mib*unit-1,flags);
        cursor+=mib*unit; p->setLabel(label); PartitionInfo::setMountPoint(p,mount); PartitionInfo::setFormat(p,fs!=FileSystem::Type::Unformatted); m_core->createPartition(d,p,flags);
    };
    if(!hasEsp) add(512,FileSystem::Type::Fat32,QStringLiteral("/boot/efi"),QStringLiteral("EFI System Partition"),KPM_PARTITION_FLAG(Boot));
    add(qRound64(root->value()*1024),FileSystem::Type::Ext4,QStringLiteral("/"),QStringLiteral("BitcoinCoreVault"),KPM_PARTITION_FLAG(None));
    if(reserve->isChecked()) add(qRound64(other->value()*1024),FileSystem::Type::Unformatted,QString(),QString::fromLatin1(companionLabel),KPM_PARTITION_FLAG(None));
    assignEsp(); refresh();
}
void PartitionPage::eraseDisk()
{
    auto* d=device(); if(!d || !PartUtils::isEfiSystem()) return;
    if(QMessageBox::warning(this,tr("Erase selected disk"),tr("Remove every partition on %1 (%2)? All files on this physical disk will be erased when you confirm Review. Other physical disks are preserved.").arg(d->deviceNode(),d->name()),QMessageBox::Yes|QMessageBox::Cancel,QMessageBox::Cancel)!=QMessageBox::Yes) return;
    onRevertClicked(); d=device(); if(!d) return;
    m_core->createPartitionTable(d,PartitionTable::gpt);
    QCoreApplication::instance()->setProperty("coreInstallEraseDisk",d->deviceNode()); refresh();
    for(int i=0;i<m_table->topLevelItemCount();++i) {
        auto* item=m_table->topLevelItem(i);
        auto* p=reinterpret_cast<Partition*>(item->data(0,Qt::UserRole).value<quintptr>());
        if(isPartitionFreeSpace(p)) {m_table->setCurrentItem(item);break;}
    }
}
