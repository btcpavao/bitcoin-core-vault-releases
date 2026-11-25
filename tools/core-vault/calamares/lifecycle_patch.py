#!/usr/bin/python3
"""Keep preview resets on the GUI thread and report installation failure on exit."""
from pathlib import Path
import base_patch as b

ADDITIONAL = ['src/modules/partition/core/BootLoaderModel.cpp',
              'src/modules/partition/core/PartitionModel.cpp', 'debian/control',
              'src/calamares/main.cpp']


def patch_tree(root):
    root = Path(root)
    path = root / 'src/modules/partition/core/BootLoaderModel.cpp'
    s = path.read_text()
    s = b.once(s, '#include <QComboBox>', '#include <QComboBox>\n#include <QSignalBlocker>',
               'boot model signal blocker')
    s = b.replace_function(s, 'BootLoaderModel::init( const QList< Device* >& devices )', r'''    beginResetModel();
    {
        const QSignalBlocker modelSignals(this);
        m_devices = devices;
        updateInternal();
    }
    endResetModel();''')
    s = b.replace_function(s, 'BootLoaderModel::update()', r'''    beginResetModel();
    {
        const QSignalBlocker modelSignals(this);
        updateInternal();
    }
    endResetModel();''')
    s = b.once(s, '    clear();\n    createMbrItems();',
        '    // QStandardItemModel::clear() begins another model reset.\n'
        '    // The caller already owns a single reset and blocks internal signals.\n'
        '    removeRows(0, rowCount());\n    createMbrItems();',
        'single boot model reset')
    path.write_text(s)

    path = root / 'src/modules/partition/core/PartitionModel.cpp'
    s = b.replace_function(path.read_text(),
        'PartitionModel::init( Device* device, const OsproberEntryList& osproberEntries )',
        r'''    // Reset notifications can synchronously query this model. Never hold
    // its nonrecursive data mutex while notifying views.
    beginResetModel();
    {
        QMutexLocker lock(&m_lock);
        m_device = device;
        m_osproberEntries = osproberEntries;
    }
    endResetModel();''')
    path.write_text(s)

    path = root / 'src/modules/partition/core/PartitionCoreModule.cpp'
    s = b.once(path.read_text(),
        '    Device* newDev = backend->scanDevice( devInfo->device->deviceNode() );\n'
        '    devInfo->device.reset( newDev );',
        '    const QString devicePath = devInfo->device->deviceNode();\n'
        '    Device* newDev = backend->scanDevice(devicePath);\n'
        '    // Model reset observers may still query the previous tree while\n'
        '    // each model is rebound. Release it only after all rebinding ends.\n'
        '    auto previousDevice = std::move(devInfo->device);\n'
        '    devInfo->device.reset( newDev );',
        'retain old device through model rebinding')
    # Qt6 disables deprecated QScopedPointer transfer APIs in this build.
    # Keep exclusive ownership and move the former device into the local guard.
    s = b.once(s, '    QScopedPointer< Device > device;',
               '    std::unique_ptr<Device> device;', 'movable exclusive device owner')
    s = '#include <memory>\n#include <utility>\n' + s
    s = s.replace('device.data()', 'device.get()')
    s = b.once(s, '!info->device.isNull()', 'info->device', 'unique device null check')
    path.write_text(s)

    path = root / 'src/modules/partition/gui/ChoicePage.cpp'
    s = path.read_text()
    if '#include <QSignalBlocker>' not in s:
        s = '#include <QSignalBlocker>\n' + s
    s = b.once(s, 'void\nChoicePage::applyDeviceChoice()', r'''static void
restoreDeviceChoiceByPath(PartitionCoreModule* core, QComboBox* combo, const QString& path)
{
    const QSignalBlocker driveSignals(combo);
    int found = -1;
    auto* model = core->deviceModel();
    for (int row = 0; row < model->rowCount(); ++row)
    {
        auto* device = model->deviceForIndex(model->index(row, 0));
        if (device && device->deviceNode() == path)
        {
            found = row;
            break;
        }
    }
    combo->setCurrentIndex(found);
}

void
ChoicePage::applyDeviceChoice()''', 'restore physical device selection by path')
    s = b.replace_function(s, 'ChoicePage::applyDeviceChoice()', r'''    if (!selectedDevice())
    {
        hideButtons();
        return;
    }
    const QString selectedPath = selectedDevice()->deviceNode();
    if (m_core->isDirty())
    {
        // Reverting replaces Device objects and resets Qt models. Do this on
        // the owning GUI thread; a worker must not mutate live view models.
        const QSignalBlocker driveSignals(m_drivesCombo);
        m_core->revertAllDevices();
        restoreDeviceChoiceByPath(m_core, m_drivesCombo, selectedPath);
    }
    if (!selectedDevice())
    {
        m_config->setInstallChoice(InstallChoice::NoChoice);
        checkInstallChoiceRadioButton(InstallChoice::NoChoice);
        hideButtons();
        updateNextEnabled();
        return;
    }
    continueApplyDeviceChoice();''')
    s = b.replace_function(s, 'ChoicePage::applyActionChoice( InstallChoice choice )', r'''    cDebug() << "InstallChoice" << choice << Config::installChoiceNames().find(choice);
    m_beforePartitionBarsView->selectionModel()->disconnect(SIGNAL(currentRowChanged(QModelIndex,QModelIndex)));
    const auto priorSelection = m_beforePartitionBarsView->selectionModel()->currentIndex();
    const QString selectedPath = selectedDevice() ? selectedDevice()->deviceNode() : QString();
    m_beforePartitionBarsView->selectionModel()->clearSelection();
    m_beforePartitionBarsView->selectionModel()->clearCurrentIndex();

    // These resets destroy preview partitions and update GUI-owned models.
    // Keep the reset and the subsequent preview together on the GUI thread,
    // then resolve selectedDevice() again instead of retaining its old pointer.
    const bool resetPreview = choice != InstallChoice::NoChoice && m_core->isDirty();
    if (resetPreview)
    {
        const QSignalBlocker driveSignals(m_drivesCombo);
        m_core->revertDevice(selectedDevice());
        restoreDeviceChoiceByPath(m_core, m_drivesCombo, selectedPath);
    }
    if (!selectedDevice())
    {
        m_config->setInstallChoice(InstallChoice::NoChoice);
        checkInstallChoiceRadioButton(InstallChoice::NoChoice);
        hideButtons();
        updateNextEnabled();
        return;
    }

    switch (choice)
    {
    case InstallChoice::Erase:
    {
        auto gs = Calamares::JobQueue::instance()->globalStorage();
        PartitionActions::Choices::AutoPartitionOptions options {
            gs->value("defaultPartitionTableType").toString(),
            m_config->eraseFsType(),
            m_config->luksFileSystemType(),
            m_encryptWidget->passphrase(),
            gs->value("efiSystemPartition").toString(),
            Calamares::GiBtoBytes(gs->value("requiredStorageGiB").toDouble()),
            m_config->swapChoice()
        };
        PartitionActions::doAutopartition(m_core, selectedDevice(), options);
        Q_EMIT deviceChosen();
        break;
    }
    case InstallChoice::Replace:
        connect(m_beforePartitionBarsView->selectionModel(),
                &QItemSelectionModel::currentRowChanged,
                this, &ChoicePage::onPartitionToReplaceSelected, Qt::UniqueConnection);
        if (!resetPreview && priorSelection.isValid())
            m_beforePartitionBarsView->selectionModel()->setCurrentIndex(priorSelection, QItemSelectionModel::Select);
        break;
    case InstallChoice::Alongside:
        connect(m_beforePartitionBarsView->selectionModel(),
                &QItemSelectionModel::currentRowChanged,
                this, &ChoicePage::doAlongsideSetupSplitter, Qt::UniqueConnection);
        break;
    case InstallChoice::Manual:
    case InstallChoice::NoChoice:
        break;
    }
    updateNextEnabled();
    updateActionChoicePreview(choice);''')
    s = b.once(s,
        '             QOverload< int >::of( &QComboBox::currentIndexChanged ),\n'
        '             this,\n'
        '             [ this ]( int newIndex )',
        '             QOverload< int >::of( &QComboBox::activated ),\n'
        '             this,\n'
        '             [ this ]( int newIndex )',
        'bootloader changes only on user activation')
    s = b.once(s,
        '''    connect( m_core->bootLoaderModel(),
             &QAbstractItemModel::modelReset,
             [ this ]()
             {
                 if ( !m_bootloaderComboBox.isNull() )
                 {
                     Calamares::restoreSelectedBootLoader( *m_bootloaderComboBox, m_core->bootLoaderInstallPath() );
                 }
             } );''',
        '''    connect( m_core->bootLoaderModel(),
             &QAbstractItemModel::modelReset,
             comboForBootloader,
             [ this, comboForBootloader ]()
             {
                 const QSignalBlocker modelSignals(comboForBootloader);
                 Calamares::restoreSelectedBootLoader(*comboForBootloader, m_core->bootLoaderInstallPath());
             } );''',
        'bootloader reset receiver lifetime and thread context')
    path.write_text(s)

    path = root / 'src/modules/partition/PartitionViewStep.cpp'
    s = path.read_text()
    s = b.once(s, '    m_choicePage = new ChoicePage( m_config );',
        '    // ChoicePage::init immediately evaluates available storage.\n'
        '    m_config->fillGSSecondaryConfiguration();\n'
        '    m_choicePage = new ChoicePage( m_config );',
        'storage requirement before choice page initialization')
    path.write_text(s)

    path = root / 'debian/control'
    s = b.once(path.read_text(),
        'Depends: os-prober, ${misc:Depends}, ${shlibs:Depends}',
        'Depends: os-prober, qml6-module-qtquick-window, ${misc:Depends}, ${shlibs:Depends}',
        'shipped Qt6 presentation runtime dependency')
    path.write_text(s)


    path = root / 'src/calamares/main.cpp'
    s = b.once(path.read_text(), '#include <QDir>', '#include <QDir>\n#include <QVariant>',
               'failure exit property value')
    s = b.once(s, '    return a.exec();',
        '    const int result = a.exec();\n'
        '    // Closing the failure page must not look like a successful installation.\n'
        '    return result == 0 && a.property("coreVaultInstallationFailed").toBool() ? 1 : result;',
        'reported installation failure exit status')
    path.write_text(s)
