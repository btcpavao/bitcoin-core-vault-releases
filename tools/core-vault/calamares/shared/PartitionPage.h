// SPDX-License-Identifier: GPL-3.0-or-later
// Bounded native partition editor: no resizing, moving, or cross-disk jobs.
#pragma once
#include <QWidget>
class Config; class PartitionCoreModule; class Device; class Partition;
class QComboBox; class QTreeWidget; class QLabel; class QPushButton;
class PartitionPage : public QWidget
{
    Q_OBJECT
public:
    explicit PartitionPage(PartitionCoreModule*, const Config&, QWidget* parent = nullptr);
    ~PartitionPage() override = default;
    void onRevertClicked();
    int selectedDeviceIndex();
    void selectDeviceByIndex(int);
private:
    Device* device() const;
    Partition* selection() const;
    void refresh();
    void updateSelectionActions();
    void revertToDevicePath(const QString&);
    void edit();
    void createLayout();
    void eraseDisk();
    void setRoot(Partition*);
    bool assignEsp();
    PartitionCoreModule* m_core;
    const Config& m_config;
    QComboBox* m_drive;
    QTreeWidget* m_table;
    QLabel* m_status;
    QPushButton *m_create, *m_edit, *m_erase;
    bool m_busy = false;
};
