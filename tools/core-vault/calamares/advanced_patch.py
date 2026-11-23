#!/usr/bin/python3
"""Bounded native Advanced editor and plan guard for Debian Calamares 3.3.14-1.

Runs after the existing visual postpass; all established shell geometry is kept.
No block devices are opened by this source transformer.
"""
from pathlib import Path
import base_patch as b
ADDITIONAL = ['src/modules/partition/gui/PartitionPage.h',
              'src/modules/partition/gui/PartitionPage.cpp',
              'src/modules/partition/core/PartitionCoreModule.h']

def patch_tree(root, product='vault'):
    assert product in ('node','vault')
    root=Path(root); templates=Path(__file__).with_name('shared')
    def read(name):
        return (templates/name).read_text().replace('CORE_PRODUCT_NODE','true' if product=='node' else 'false').replace('CORE_PRODUCT_KEY',product)
    for name in ('PartitionPage.h','PartitionPage.cpp'):
        (root/'src/modules/partition/gui'/name).write_text(read(name))
    (root/'src/modules/partition/core/CoreOfflineGuard.h').write_text(read('CoreOfflineGuard.h'))
    path=root/'src/modules/partition/core/PartitionCoreModule.h';s=path.read_text()
    s=s.replace('#include <QList>','#include <QList>\n#include <QJsonObject>')
    s=b.once(s,'    Calamares::JobList jobs( const Config* ) const;',
        '    Calamares::JobList jobs( const Config* ) const;\n'
        '    QJsonObject installPlan(const Config*) const;\n'
        '    QString validateInstallPlan(const Config*) const;', 'native plan API')
    path.write_text(s)
    path=root/'src/modules/partition/core/PartitionCoreModule.cpp';s=path.read_text()
    s='#include <QCoreApplication>\n#include <QJsonArray>\n#include <QVariant>\n'+s
    start=s.index('    // CORE_OFFLINE_INTEGRATION: validate selected disk immediately before writes.')
    end=s.index('\n#ifdef DEBUG_PARTITION_UNSAFE',start)
    s=s[:start]+'    // Re-check identity, every affected partition and the actual queued jobs.\n    lst << Calamares::job_ptr(new CoreOfflineDiskGuard(installPlan(config)));\n'+s[end:]
    s=b.once(s,'    lst << Calamares::job_ptr( new FillGlobalStorageJob( config, devices, m_bootLoaderInstallPath ) );',
        '    lst << Calamares::job_ptr(new CoreReservedSpaceJob());\n    lst << Calamares::job_ptr( new FillGlobalStorageJob( config, devices, m_bootLoaderInstallPath ) );', 'prepare only reviewed reservations')
    s+=read('PlanMethods.cpp.inc');path.write_text(s)
    path=root/'src/modules/partition/gui/ChoicePage.cpp';s=path.read_text()
    s=s.replace('m_drivesCombo = new QComboBox( this );','m_drivesCombo = new QComboBox( this );\n    m_drivesCombo->setObjectName(QStringLiteral("coreInstallDrive"));')
    s=s.replace('Select one internal drive. The selected drive will be completely erased and dedicated to Bitcoin Core Vault.',
        'Select an internal drive and choose how to install Bitcoin Core Vault.')
    s=s.replace('Everything currently stored on the selected drive will be permanently erased.',
        'Choose an installation method. You can review every change before installation.')
    s=b.once(s,'    m_itemsScrollArea->hide();','    m_itemsScrollArea->show();\n    m_itemsScrollArea->setMinimumHeight(150);\n    m_itemsScrollArea->setMaximumHeight(190);','show two installation methods')
    s=b.once(s,'        m_config->setInstallChoice( InstallChoice::Erase ); // CORE_OFFLINE_INTEGRATION\n        checkInstallChoiceRadioButton( InstallChoice::Erase );',
        '        m_config->setInstallChoice( InstallChoice::NoChoice );\n        checkInstallChoiceRadioButton( InstallChoice::NoChoice );','no automatic erase selection')
    s=b.once(s,'    force_uncheck(m_grp, m_somethingElseButton);',
        '    m_somethingElseButton->show();\n    m_somethingElseButton->setObjectName(QStringLiteral("coreInstallMethodAdvanced"));\n    m_eraseButton->setObjectName(QStringLiteral("coreInstallMethodErase"));\n    m_somethingElseButton->setEnabled(m_isEfi);\n    m_eraseButton->setIcon(QIcon());\n    m_somethingElseButton->setIcon(QIcon());\n    updateChoiceButtonsTr();', 'keep bounded manual option')
    s=b.replace_function(s,'ChoicePage::updateChoiceButtonsTr()',r'''    if(m_somethingElseButton) m_somethingElseButton->setText(m_isEfi
        ? tr("<strong>Advanced partitioning</strong><br/>Choose a partition or create a layout with reserved space.")
        : tr("<strong>Advanced partitioning</strong><br/>Restart this USB in UEFI mode to use this option."));
    if(m_eraseButton) m_eraseButton->setText(tr("<strong>Install to disk</strong><br/>Erase the selected physical disk and install Bitcoin Core Vault."));''')
    s=b.append_function(s,'ChoicePage::updateActionDescriptionsTr()',
        '    updateChoiceButtonsTr();\n    m_messageLabel->hide();')
    s=b.append_function(s,'ChoicePage::onActionChanged()',r'''    QCoreApplication::instance()->setProperty("coreInstallEraseDisk",QString());
    if(auto* warning=findChild<QLabel*>(QStringLiteral("coreOfflineEraseWarning"))) {
        warning->setText(m_config->installChoice()==InstallChoice::Erase
            ? tr("Everything on the selected physical disk will be permanently erased. Other physical disks are preserved.")
            : m_config->installChoice()==InstallChoice::Manual
                ? tr("Choose the exact target partition in the next view. Existing partitions will not be resized or moved.")
                : tr("Choose an installation method. You can review every change before installation."));
    }''')
    s='#include <QCoreApplication>\n#include <QVariant>\n'+s;path.write_text(s)
    path=root/'src/modules/partition/PartitionViewStep.cpp';s=path.read_text()
    s='#include <QJsonArray>\n#include <QJsonObject>\n#include <QCoreApplication>\n#include <QVariant>\n'+s
    s=b.replace_function(s,'PartitionViewStep::prettyStatus() const',r'''    const auto p=m_core->installPlan(m_config);
    return tr("<b>Installation drive</b><br/>%1<br/>%2").arg(p.value("target").toString().toHtmlEscaped(),
        p.value("mode").toString()==QStringLiteral("advanced") ? tr("Install on the selected partition; preserve other partitions.") : tr("Erase the selected physical disk."));''')
    s=b.replace_function(s,'PartitionViewStep::createSummaryWidget() const',read('Review.cpp.inc'))
    # The bounded editor validates EFI itself. Upstream warning-only generic checks
    # must not create an apparent override of a failed plan guard.
    s=b.replace_function(s,'PartitionViewStep::onLeave()',r'''    if(m_widget->currentWidget()==m_choicePage) m_choicePage->onLeave();''')
    path.write_text(s)
    path=root/'src/modules/summary/SummaryViewStep.cpp';s=path.read_text()
    s='#include <QCoreApplication>\n#include <QVariant>\n'+s
    s=s.replace('I understand that everything on the selected drive will be erased.',
        'I have reviewed the selected disk, formatting and preservation above, and confirm these changes.')
    s=s.replace('Q_EMIT nextStatusChanged(checked);','Q_EMIT nextStatusChanged(checked && QCoreApplication::instance()->property("coreInstallPlanValid").toBool());')
    s=s.replace('return consent && consent->isChecked();','return consent && consent->isChecked() && QCoreApplication::instance()->property("coreInstallPlanValid").toBool();')
    s=b.append_function(s,'SummaryViewStep::onActivate()',r'''    if(auto* consent=m_widget->findChild<QCheckBox*>(QStringLiteral("coreVaultEraseConsent")))
        consent->setEnabled(QCoreApplication::instance()->property("coreInstallPlanValid").toBool());''')
    path.write_text(s)
    path=root/'src/calamares/CalamaresWindow.cpp';s=path.read_text().replace('Erase drive and install','Install Bitcoin Core Vault');path.write_text(s)
