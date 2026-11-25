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
#include <kpmcore/fs/filesystemfactory.h>
#include <QCheckBox>
#include <QComboBox>
#include <QCoreApplication>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHeaderView>
#include <QLabel>
#include <QProcess>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMessageBox>
#include <QPushButton>
#include <QScreen>
#include <QSignalBlocker>
#include <QScopedValueRollback>
#include <QVariantMap>
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
// Keep the new editors compact even when the live window manager maximizes
// ordinary dialogs. The fixed size is calculated after stylesheet polish and
// word wrapping, so the visible controls fit the existing 800x600 minimum.
static void preparePartitionDialog(QDialog& dialog, QFormLayout& form)
{
    dialog.setWindowModality(Qt::WindowModal);
    dialog.setWindowFlag(Qt::WindowMaximizeButtonHint, false);
    dialog.setSizeGripEnabled(false);
    form.setContentsMargins(20, 16, 20, 16);
    form.setHorizontalSpacing(16);
    form.setVerticalSpacing(12);
    form.setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
    dialog.ensurePolished();
    QWidget* parent = dialog.parentWidget()->window();
    QRect available = parent->frameGeometry();
    if (parent->screen()) available = available.intersected(parent->screen()->availableGeometry());
    available = available.adjusted(20, 20, -20, -20);
    const int width = qMin(560, available.width());
    const int wrappedHeight = form.totalHeightForWidth(width);
    const int height = wrappedHeight >= 0 ? wrappedHeight : form.sizeHint().height();
    dialog.setFixedSize(width, height);
    dialog.move(available.center() - dialog.rect().center());
}
static bool espCandidate(const Partition* p)
{
    return p && !isPartitionFreeSpace(p) && !isPartitionNew(p)
        && p->fileSystem().type() == FileSystem::Type::Fat32
        && p->capacity() >= 128*MiB && PartUtils::isEfiBootable(p);
}

// A separate ESP can replace an existing mount assignment without changing
// that partition. Do not offer repeated ESP creation for an already queued ESP.
static Partition* assignedExistingEsp(Device* d)
{
    if(!PartUtils::isEfiSystem() || !d || !d->partitionTable()) return nullptr;
    for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it)
        if(PartitionInfo::mountPoint(*it)==QStringLiteral("/boot/efi"))
            return espCandidate(*it) ? *it : nullptr;
    return nullptr;
}

static bool biosBootPartition(const Partition* p)
{
    return p && !isPartitionFreeSpace(p)
        && PartitionInfo::flags(p).testFlag(KPM_PARTITION_FLAG(BiosGrub));
}
static bool supportedTable(Device* d)
{
    return d && d->partitionTable()
        && (d->partitionTable()->type()==PartitionTable::gpt
            || (!PartUtils::isEfiSystem() && KPMHelpers::isMSDOSPartition(d->partitionTable()->type())));
}
static bool missingTable(Device* d)
{
    return d && (!d->partitionTable() || d->partitionTable()->type()==PartitionTable::unknownTableType);
}
static bool hasBootPartition(Device* d)
{
    if(!supportedTable(d)) return false;
    if(!PartUtils::isEfiSystem() && KPMHelpers::isMSDOSPartition(d->partitionTable()->type())) return true;
    for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it) {
        if(PartUtils::isEfiSystem()) {
            if(espCandidate(*it) || PartitionInfo::mountPoint(*it)==QStringLiteral("/boot/efi")) return true;
        } else if(biosBootPartition(*it) && (*it)->capacity()>=MiB) return true;
    }
    return false;
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
    m_drive = new QComboBox(this); m_drive->setObjectName(QStringLiteral("corePartitionDrive")); m_drive->setModel(core->deviceModel()); row->addWidget(m_drive,1);
    layout->addLayout(row);
    m_table = new QTreeWidget(this); m_table->setObjectName(QStringLiteral("corePartitionTable"));
    m_table->setHeaderLabels({tr("Partition"),tr("Size"),tr("Filesystem"),tr("Mount point"),tr("Format")});
    m_table->setRootIsDecorated(false); m_table->setSelectionMode(QAbstractItemView::SingleSelection);
    m_table->setMinimumHeight(150); m_table->header()->setSectionResizeMode(QHeaderView::ResizeToContents);
    m_table->header()->setSectionResizeMode(0,QHeaderView::Stretch); layout->addWidget(m_table,1);
    auto* buttons = new QHBoxLayout;
    m_create = new QPushButton(tr("Create layout…"),this);
    m_edit = new QPushButton(tr("Edit…"),this);
    m_erase = new QPushButton(tr("Erase selected disk…"),this);
    auto* revert = new QPushButton(tr("Revert changes"),this);
    m_create->setObjectName(QStringLiteral("coreCreateLayout")); m_edit->setObjectName(QStringLiteral("coreEditPartition"));
    m_erase->setObjectName(QStringLiteral("coreEraseDisk")); revert->setObjectName(QStringLiteral("coreRevertPartitions"));
    buttons->addWidget(m_create); buttons->addWidget(m_edit); buttons->addStretch();
    buttons->addWidget(m_erase); buttons->addWidget(revert); layout->addLayout(buttons);
    m_status = new QLabel(this); m_status->setWordWrap(true);
    m_status->setObjectName(QStringLiteral("coreOfflineEraseWarning")); layout->addWidget(m_status);
    connect(m_create,&QPushButton::clicked,this,&PartitionPage::createLayout);
    connect(m_edit,&QPushButton::clicked,this,&PartitionPage::edit);
    connect(m_erase,&QPushButton::clicked,this,&PartitionPage::eraseDisk);
    connect(revert,&QPushButton::clicked,this,&PartitionPage::onRevertClicked);
    connect(m_table,&QTreeWidget::itemDoubleClicked,this,[this] { edit(); });
    connect(m_table,&QTreeWidget::itemSelectionChanged,this,&PartitionPage::updateSelectionActions);
    connect(m_drive,QOverload<int>::of(&QComboBox::activated),this,[this](int) {
        if(m_busy) return;
        // Programmatic model updates are not a request to change disks.
        auto* selected=device();
        const QString path=selected?selected->deviceNode():QString();
        revertToDevicePath(path);
    });
    refresh();
}
Device* PartitionPage::device() const
{
    return m_core->deviceModel()->deviceForIndex(m_core->deviceModel()->index(m_drive->currentIndex(),0));
}
Partition* PartitionPage::selection() const
{
    auto* item=m_table->currentItem(); auto* d=device();
    if(!item || !d || !d->partitionTable()) return nullptr;
    // Model resets and preview jobs replace Device/Partition objects. Rows keep
    // only value identities; never dereference a pointer saved before a reset.
    const auto identity=item->data(0,Qt::UserRole).toMap();
    if(identity.value(QStringLiteral("device")).toString()!=d->deviceNode()) return nullptr;
    for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it) {
        auto* p=*it;
        if(identity.value(QStringLiteral("first")).toLongLong()==p->firstSector()
            && identity.value(QStringLiteral("last")).toLongLong()==p->lastSector()
            && identity.value(QStringLiteral("path")).toString()==p->partitionPath()
            && identity.value(QStringLiteral("free")).toBool()==isPartitionFreeSpace(p)
            && identity.value(QStringLiteral("new")).toBool()==isPartitionNew(p)) return p;
    }
    return nullptr;
}
int PartitionPage::selectedDeviceIndex() { return m_drive->currentIndex(); }
void PartitionPage::selectDeviceByIndex(int n)
{
    const QSignalBlocker block(m_drive); m_drive->setCurrentIndex(n); refresh();
}
void PartitionPage::updateSelectionActions()
{
    if(m_busy) return;
    auto* p=selection(); auto* d=device(); const bool enabled=supportedTable(d);
    const bool separateEsp=m_core->hasRootMountPoint() && assignedExistingEsp(d);
    m_create->setEnabled(missingTable(d) || (enabled && p && isPartitionFreeSpace(p)
        && (!m_core->hasRootMountPoint() || !hasBootPartition(d) || separateEsp)));
    m_edit->setEnabled(enabled && p && !isPartitionFreeSpace(p) && !isPartitionNew(p)
        && !p->roles().has(PartitionRole::Extended) && !biosBootPartition(p));
}
void PartitionPage::revertToDevicePath(const QString& path)
{
    if(m_busy) return;
    {
        const QScopedValueRollback<bool> busy(m_busy,true);
        const QSignalBlocker driveSignals(m_drive), tableSignals(m_table);
        // Invalidate the old view before reverting destroys its partition tree.
        m_table->clear();
        m_create->setEnabled(false); m_edit->setEnabled(false); m_erase->setEnabled(false);
        m_core->revertAllDevices();
        int index=-1;
        auto* model=m_core->deviceModel();
        for(int row=0;row<model->rowCount();++row) {
            auto* candidate=model->deviceForIndex(model->index(row,0));
            if(candidate && candidate->deviceNode()==path) {index=row;break;}
        }
        // Never silently fall back to another disk if the selected one vanished.
        m_drive->setCurrentIndex(index);
    }
    QCoreApplication::instance()->setProperty("coreInstallEraseDisk",QString());
    refresh();
}
void PartitionPage::onRevertClicked()
{
    auto* selected=device();
    const QString path=selected?selected->deviceNode():QString();
    revertToDevicePath(path);
}
void PartitionPage::refresh()
{
    const QSignalBlocker tableSignals(m_table);
    m_table->clear(); auto* d=device();
    m_create->setEnabled(false); m_edit->setEnabled(false);
    m_erase->setEnabled(d!=nullptr);
    m_create->setText(missingTable(d)?tr("Initialize disk…"):tr("Create layout…"));
    if(missingTable(d)) m_create->setEnabled(true);
    if(!d) { m_status->setText(tr("No eligible internal drive is available.")); return; }
    m_core->setBootLoaderInstallPath(d->deviceNode());
    QString reservedPath;
    if(!m_core->isDirty()) {
        QProcess probe;
        probe.start(QStringLiteral("/usr/bin/python3"),{QStringLiteral("/usr/lib/core-vault-installer/disk_safety.py"),QStringLiteral("reservations"),d->deviceNode(),isNode?QStringLiteral("node"):QStringLiteral("vault")});
        if(probe.waitForStarted(3000) && probe.waitForFinished(12000) && probe.exitCode()==0) {
            const auto reservationEntries=QJsonDocument::fromJson(probe.readAllStandardOutput()).array();
            if(reservationEntries.size()==1) reservedPath=reservationEntries.first().toObject().value("path").toString();
        } else {probe.kill();probe.waitForFinished(1000);}
    }
    if(d->partitionTable()) for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it) {
        auto* p=*it; const bool free=isPartitionFreeSpace(p);
        QString name=free ? tr("Unallocated space") : p->partitionPath();
        if(name.isEmpty()) name=tr("New partition");
        if(!reservedPath.isEmpty() && p->partitionPath()==reservedPath) name+=tr(" — verified reserved space");
        if(!free && !p->label().isEmpty()) name += QStringLiteral(" — ")+p->label();
        if(!free && p->roles().has(PartitionRole::Extended)) name+=tr(" — extended container");
        else if(!free && p->roles().has(PartitionRole::Logical)) name+=tr(" — logical");
        else if(biosBootPartition(p)) name+=tr(" — BIOS boot");
        auto* item=new QTreeWidgetItem(m_table,{name,sizeText(p->capacity()),
            free ? QStringLiteral("—") : FileSystem::nameForType(p->fileSystem().type()),
            PartitionInfo::mountPoint(p),PartitionInfo::format(p) ? tr("Yes") : tr("No")});
        item->setData(0,Qt::UserRole,QVariantMap{
            {QStringLiteral("device"),d->deviceNode()},
            {QStringLiteral("path"),p->partitionPath()},
            {QStringLiteral("first"),QVariant::fromValue<qlonglong>(p->firstSector())},
            {QStringLiteral("last"),QVariant::fromValue<qlonglong>(p->lastSector())},
            {QStringLiteral("free"),free},{QStringLiteral("new"),isPartitionNew(p)}});
        if(!reservedPath.isEmpty() && p->partitionPath()==reservedPath) m_table->setCurrentItem(item);
    }
    updateSelectionActions();
    if(missingTable(d)) {
        m_status->setText(tr("No supported partition table was detected. Initialize disk creates a new GPT layout after confirmation. Existing unpartitioned data on this disk will be replaced.")); return;
    }
    if(!supportedTable(d)) {
        m_status->setText(PartUtils::isEfiSystem()
            ? tr("UEFI installation requires a GPT disk. An existing MBR installation can be preserved by restarting this USB in Legacy BIOS mode. Erase selected disk explicitly replaces the whole disk with GPT.")
            : tr("Legacy BIOS installation supports GPT and MBR disks. Erase selected disk explicitly replaces an unsupported partition table with GPT. Existing partitions are never converted or resized automatically.")); return;
    }
    if(m_core->hasRootMountPoint()) {
        auto error=m_core->validateInstallPlan(&m_config);
        const bool erase=m_core->installPlan(&m_config).value("mode").toString()==QStringLiteral("erase-layout");
        m_status->setText(!error.isEmpty() ? error : erase
            ? tr("Every existing partition on the selected physical disk will be erased and replaced by this layout. Other physical disks are preserved. Review lists the exact operations.")
            : PartUtils::isEfiSystem()
                ? tr("The selected root will be formatted as ext4. Existing EFI partitions are preserved without formatting. A new EFI partition uses only unallocated space. Review lists the boot partition and all planned operations.")
                : tr("The selected root will be formatted as ext4. The BIOS bootloader on this disk will be replaced. Other data partitions and physical disks are preserved; other operating systems may need boot menu configuration."));
    } else m_status->setText(tr("Select a partition and choose Edit to install there. Create layout requires selected unallocated space and can reserve space for %1. Existing partitions are never shrunk or moved automatically.").arg(QString::fromLatin1(companionName)));
}
bool PartitionPage::assignEsp()
{
    auto* d=device(); if(!PartUtils::isEfiSystem() || !d || !d->partitionTable()) return false;
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
    auto* d=device(); if(!d || !p || p->roles().has(PartitionRole::Extended) || biosBootPartition(p)) return;
    // Keep the actual partition entry, PARTUUID and logical partition number.
    // Deleting and recreating a logical partition would renumber its siblings.
    // KPM's format operation changes the filesystem and system type in place.
    if(p->fileSystem().type()!=FileSystem::Type::Ext4) {
        auto* filesystem=FileSystemFactory::create(FileSystem::Type::Ext4,p->firstSector(),p->lastSector(),d->logicalSize());
        if(!filesystem) return;
        p->deleteFileSystem(); p->setFileSystem(filesystem);
        p->setRoles(PartitionRole(p->roles().has(PartitionRole::Logical)?PartitionRole::Logical:PartitionRole::Primary));
    }
    // KPM otherwise prefers the old explicit partition type over the new
    // filesystem type (for example NTFS/MBR 0x07). Let it derive Linux/ext4.
    p->setType(QString());
    PartitionInfo::setMountPoint(p,QStringLiteral("/")); PartitionInfo::setFormat(p,true);
    m_core->formatPartition(d,p);
    if(!PartUtils::isEfiSystem() && KPMHelpers::isMSDOSPartition(d->partitionTable()->type()) && !p->roles().has(PartitionRole::Logical)) {
        bool hasActive=false;
        for(const auto* part:d->partitionTable()->children())
            if(!isPartitionFreeSpace(part) && PartitionInfo::flags(part).testFlag(KPM_PARTITION_FLAG(Boot))) hasActive=true;
        if(!hasActive) m_core->setPartitionFlags(d,p,PartitionInfo::flags(p)|KPM_PARTITION_FLAG(Boot));
    }
    assignEsp(); refresh();
}
void PartitionPage::edit()
{
    auto* p=selection(); auto* d=device();
    if(!supportedTable(d) || !p || isPartitionFreeSpace(p) || isPartitionNew(p)
        || p->roles().has(PartitionRole::Extended) || biosBootPartition(p)) return;
    if(PartUtils::isEfiSystem() && espCandidate(p)) {
        if(QMessageBox::question(this,tr("Use EFI partition"),tr("Use %1 at /boot/efi without formatting? Existing EFI files will be preserved.").arg(p->partitionPath()))!=QMessageBox::Yes) return;
        for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it)
            if(PartitionInfo::mountPoint(*it)==QStringLiteral("/boot/efi")) PartitionInfo::setMountPoint(*it,QString());
        PartitionInfo::setMountPoint(p,QStringLiteral("/boot/efi")); PartitionInfo::setFormat(p,false);
        m_core->refreshPartition(d,p); refresh(); return;
    }
    if(m_core->hasRootMountPoint()) { QMessageBox::information(this,tr("Root already selected"),tr("Choose Revert changes before selecting a different root partition.")); return; }
    if(p->capacity()<rootMinimum*GiB) { QMessageBox::warning(this,tr("Partition too small"),tr("The installation needs at least %1 GiB.").arg(rootMinimum)); return; }
    QDialog dialog(this); dialog.setObjectName(QStringLiteral("corePartitionEditDialog")); dialog.setWindowTitle(tr("Edit partition"));
    auto* form=new QFormLayout(&dialog);
    form->addRow(tr("Partition:"),new QLabel(p->partitionPath(),&dialog));
    form->addRow(tr("Size:"),new QLabel(sizeText(p->capacity()),&dialog));
    form->addRow(tr("Filesystem:"),new QLabel(QStringLiteral("ext4"),&dialog));
    form->addRow(tr("Mount point:"),new QLabel(QStringLiteral("/"),&dialog));
    auto* format=new QCheckBox(tr("Format this partition. Its current files will be erased."),&dialog); format->setObjectName(QStringLiteral("coreFormatRootConsent")); form->addRow(format);
    auto* buttons=new QDialogButtonBox(QDialogButtonBox::Ok|QDialogButtonBox::Cancel,&dialog); form->addRow(buttons);
    buttons->button(QDialogButtonBox::Ok)->setEnabled(false);
    connect(format,&QCheckBox::toggled,buttons->button(QDialogButtonBox::Ok),&QPushButton::setEnabled);
    connect(buttons,&QDialogButtonBox::accepted,&dialog,&QDialog::accept);
    connect(buttons,&QDialogButtonBox::rejected,&dialog,&QDialog::reject);
    preparePartitionDialog(dialog, *form);
    if(dialog.exec()==QDialog::Accepted && format->isChecked()) setRoot(p);
}
void PartitionPage::createLayout()
{
    auto* d=device(); if(!d) return;
    if(missingTable(d)) {
        if(QMessageBox::warning(this,tr("Initialize disk"),
            tr("Create a new GPT partition table on %1 (%2)? Any existing unpartitioned data on this disk will be replaced when you confirm Review. Other physical disks are preserved.").arg(d->deviceNode(),d->name()),
            QMessageBox::Yes|QMessageBox::Cancel,QMessageBox::Cancel)!=QMessageBox::Yes) return;
        m_core->createPartitionTable(d,PartitionTable::gpt);
        QCoreApplication::instance()->setProperty("coreInstallEraseDisk",d->deviceNode());
        refresh();
        for(int i=0;i<m_table->topLevelItemCount();++i) {
            auto* item=m_table->topLevelItem(i);
            if(item->data(0,Qt::UserRole).toMap().value(QStringLiteral("free")).toBool()) {
                m_table->setCurrentItem(item);break;
            }
        }
    }
    auto* free=selection();
    if(!supportedTable(d) || !free || !isPartitionFreeSpace(free)) return;
    const bool efi=PartUtils::isEfiSystem();
    const bool mbr=KPMHelpers::isMSDOSPartition(d->partitionTable()->type());
    auto* parent=free->parent();
    const bool logical=mbr && parent && !parent->isRoot();
    if(logical) {
        // Appending logical partitions preserves every existing MBR PARTUUID.
        // Inserting one before another logical can change its partition number.
        for(const auto* p:parent->children()) if(!isPartitionFreeSpace(p) && p->lastSector()>free->firstSector()) {
            QMessageBox::warning(this,tr("Preserve logical partition numbers"),tr("Use unallocated space after the last logical partition, or select an existing partition for installation. Creating a logical partition here could renumber another installation.")); return;
        }
    }
    int primarySlots=4;
    if(mbr && !logical) for(const auto* p:d->partitionTable()->children()) if(!isPartitionFreeSpace(p)) --primarySlots;
    const bool hasBoot=hasBootPartition(d);
    auto* existingEsp=m_core->hasRootMountPoint()?assignedExistingEsp(d):nullptr;
    const bool separateEsp=existingEsp!=nullptr;
    const qint64 bootMiB=hasBoot && !separateEsp?0:(efi?512:2);
    const qint64 unit=MiB/d->logicalSize();
    if(unit<=0) return;
    const qint64 first=qMax(unit,((free->firstSector()+unit-1)/unit)*unit)+(logical?unit:0);
    const qint64 end=((free->lastSector()+1)/unit)*unit;
    const qint64 spanMiB=qMax(qint64(0),(end-first)/unit);
    // Newly created partitions have no on-disk active flags. Keep desired
    // flags in the preview and the queued SetPartFlagsJob so KPM writes them.
    auto addBoot=[&](qint64 at) {
        const auto flags=efi?KPM_PARTITION_FLAG(Boot):KPM_PARTITION_FLAG(BiosGrub);
        auto* boot=KPMHelpers::createNewPartition(d->partitionTable(),*d,PartitionRole(PartitionRole::Primary),
            efi?FileSystem::Type::Fat32:FileSystem::Type::Unformatted,QString(),at,at+bootMiB*unit-1,KPM_PARTITION_FLAG(None));
        boot->setLabel(efi?QStringLiteral("EFI System Partition"):QStringLiteral("BIOS boot"));
        PartitionInfo::setMountPoint(boot,efi?QStringLiteral("/boot/efi"):QString());
        PartitionInfo::setFormat(boot,efi);m_core->createPartition(d,boot,flags);
    };
    if(m_core->hasRootMountPoint()) {
        if(hasBoot && !separateEsp) {
            QMessageBox::information(this,tr("Boot space available"),efi
                ? tr("Select an existing EFI partition and choose Edit to reuse it without formatting.")
                : tr("The disk already has BIOS boot space. Review will verify it before installation.")); return;
        }
        if(spanMiB<bootMiB) {
            QMessageBox::warning(this,tr("Not enough space"),efi
                ? tr("Creating EFI requires 512 MiB of unallocated space.")
                : tr("Creating a BIOS boot partition requires 2 MiB of unallocated space.")); return;
        }
        if(separateEsp) {
            QMessageBox confirm(QMessageBox::Question,tr("Create separate EFI partition"),
                tr("Create a new 512 MiB FAT32 EFI partition in this unallocated area and use it at /boot/efi? Existing EFI partition %1 will keep its files and flags and will not be formatted. The selected root and other partition boundaries stay unchanged. Changes are written only after you confirm Review.").arg(existingEsp->partitionPath()),
                QMessageBox::NoButton,this);
            auto* create=confirm.addButton(tr("Create EFI partition"),QMessageBox::AcceptRole);
            auto* cancel=confirm.addButton(QMessageBox::Cancel);
            confirm.setDefaultButton(cancel);
            confirm.exec();
            if(confirm.clickedButton()!=create) return;
            // Only the mount assignment changes. No format or flag job is
            // queued for the existing ESP; its on-disk contents are retained.
            PartitionInfo::setMountPoint(existingEsp,QString());
            PartitionInfo::setFormat(existingEsp,false);
            addBoot(first);refresh();return;
        }
        if(QMessageBox::question(this,efi?tr("Create EFI partition"):tr("Create BIOS boot partition"),efi
            ? tr("Create a 512 MiB FAT32 EFI partition in this unallocated area? The selected root and all other data partitions keep their boundaries.")
            : tr("Create a 2 MiB unformatted BIOS boot partition in this unallocated area? The selected root and all other data partitions keep their boundaries."))!=QMessageBox::Yes) return;
        addBoot(first);refresh();return;
    }
    // Leave an extra MiB for the second EBR when two logical partitions are made.
    const qint64 availableMiB=spanMiB-bootMiB-(logical?1:0);
    if(availableMiB<rootMinimum*1024) {
        QMessageBox::warning(this,tr("Not enough unallocated space"),tr("This unallocated area is too small for the installation and its required boot space.")); return;
    }
    if(mbr && !logical && primarySlots<1) {
        QMessageBox::warning(this,tr("MBR partition limit"),tr("This MBR disk already has four primary partition entries. Select an existing partition, or use free space at the end of an existing extended partition.")); return;
    }
    QDialog dialog(this); dialog.setObjectName(QStringLiteral("coreCreateLayoutDialog")); dialog.setWindowTitle(tr("Create layout")); auto* form=new QFormLayout(&dialog);
    auto* note=new QLabel(tr("Only this unallocated area is used. Existing data partitions keep their boundaries and files."),&dialog); note->setWordWrap(true); form->addRow(note);
    auto* root=new QDoubleSpinBox(&dialog); root->setDecimals(2); root->setRange(rootMinimum,double(availableMiB)/1024); root->setSuffix(QStringLiteral(" GiB")); root->setValue(qFloor(double(availableMiB)/1024*100)/100.0);
    root->setObjectName(QStringLiteral("coreRootSizeGiB"));
    form->addRow(tr("Bitcoin Core Vault root:"),root);
    auto* reserve=new QCheckBox(tr("Reserve unformatted space for %1").arg(QString::fromLatin1(companionName)),&dialog); reserve->setObjectName(QStringLiteral("coreReserveCompanion")); form->addRow(reserve);
    if(mbr && !logical && primarySlots<2) {
        reserve->setEnabled(false);reserve->setToolTip(tr("Only one primary partition entry remains on this MBR disk."));
    }
    auto* other=new QDoubleSpinBox(&dialog); other->setDecimals(2); other->setRange(companionMinimum,qMax(double(companionMinimum),double(availableMiB)/1024-rootMinimum)); other->setSuffix(QStringLiteral(" GiB")); other->setEnabled(false); other->setObjectName(QStringLiteral("coreReservedSizeGiB")); form->addRow(tr("Reserved size:"),other);
    auto* status=new QLabel(&dialog); status->setWordWrap(true); form->addRow(status);
    auto* buttons=new QDialogButtonBox(QDialogButtonBox::Ok|QDialogButtonBox::Cancel,&dialog); form->addRow(buttons);
    auto validate=[=] {
        qint64 r=qRound64(root->value()*1024), o=reserve->isChecked()?qRound64(other->value()*1024):0;
        bool ok=r>=rootMinimum*1024 && (!reserve->isChecked() || o>=companionMinimum*1024) && r+o<=availableMiB;
        buttons->button(QDialogButtonBox::Ok)->setEnabled(ok);
        QString boot=efi?(hasBoot?tr("reuse EFI without formatting"):tr("create 512 MiB EFI"))
            : mbr?tr("Legacy BIOS; replace disk bootloader")
            : hasBoot?tr("reuse BIOS boot partition"):tr("create 2 MiB BIOS boot partition");
        status->setText(ok ? tr("Boot: %1. Remaining unallocated: %2 MiB.").arg(boot).arg(spanMiB-bootMiB-r-o-(logical && reserve->isChecked()?1:0)) : tr("Root and reserved space exceed this unallocated area."));
    };
    connect(reserve,&QCheckBox::toggled,&dialog,[=](bool checked) {
        other->setEnabled(checked);
        if(checked) {
            const double maxOther=double(availableMiB)/1024-rootMinimum;
            const double wanted=isNode ? qMin(32.0,maxOther) : qMax(double(companionMinimum),double(availableMiB)/1024-32.0);
            other->setValue(wanted); root->setValue(qFloor((double(availableMiB)/1024-other->value())*100)/100.0);
        } else root->setValue(qFloor(double(availableMiB)/1024*100)/100.0);
        validate();
    });
    connect(root,QOverload<double>::of(&QDoubleSpinBox::valueChanged),&dialog,[=](double){validate();});
    connect(other,QOverload<double>::of(&QDoubleSpinBox::valueChanged),&dialog,[=](double){validate();});
    connect(buttons,&QDialogButtonBox::accepted,&dialog,&QDialog::accept); connect(buttons,&QDialogButtonBox::rejected,&dialog,&QDialog::reject); validate();
    preparePartitionDialog(dialog, *form);
    if(dialog.exec()!=QDialog::Accepted) return;
    qint64 cursor=first;
    auto add=[&](qint64 mib,FileSystem::Type fs,const QString& mount,const QString& label,PartitionTable::Flags flags) {
        auto* p=KPMHelpers::createNewPartition(parent,*d,PartitionRole(logical?PartitionRole::Logical:PartitionRole::Primary),fs,QString(),cursor,cursor+mib*unit-1,KPM_PARTITION_FLAG(None));
        cursor+=mib*unit; p->setLabel(label); PartitionInfo::setMountPoint(p,mount); PartitionInfo::setFormat(p,fs!=FileSystem::Type::Unformatted); m_core->createPartition(d,p,flags);
    };
    if(bootMiB) {addBoot(cursor);cursor+=bootMiB*unit;}
    bool hasActive=false;
    if(mbr && !logical) for(const auto* p:d->partitionTable()->children())
        if(!isPartitionFreeSpace(p) && PartitionInfo::flags(p).testFlag(KPM_PARTITION_FLAG(Boot))) hasActive=true;
    add(qRound64(root->value()*1024),FileSystem::Type::Ext4,QStringLiteral("/"),isNode?QStringLiteral("BitcoinCoreNode"):QStringLiteral("BitcoinCoreVault"),mbr && !logical && !hasActive?KPM_PARTITION_FLAG(Boot):KPM_PARTITION_FLAG(None));
    if(reserve->isChecked()) {
        if(logical) cursor+=unit;
        add(qRound64(other->value()*1024),FileSystem::Type::Unformatted,QString(),QString::fromLatin1(companionLabel),KPM_PARTITION_FLAG(None));
    }
    assignEsp(); refresh();
}
void PartitionPage::eraseDisk()
{
    auto* d=device(); if(!d) return;
    if(QMessageBox::warning(this,tr("Erase selected disk"),tr("Remove every partition on %1 (%2)? All files on this physical disk will be erased when you confirm Review. Other physical disks are preserved.").arg(d->deviceNode(),d->name()),QMessageBox::Yes|QMessageBox::Cancel,QMessageBox::Cancel)!=QMessageBox::Yes) return;
    onRevertClicked(); d=device(); if(!d) return;
    m_core->createPartitionTable(d,PartitionTable::gpt);
    QCoreApplication::instance()->setProperty("coreInstallEraseDisk",d->deviceNode()); refresh();
    for(int i=0;i<m_table->topLevelItemCount();++i) {
        auto* item=m_table->topLevelItem(i);
        if(item->data(0,Qt::UserRole).toMap().value(QStringLiteral("free")).toBool()) {
            m_table->setCurrentItem(item);break;
        }
    }
}
